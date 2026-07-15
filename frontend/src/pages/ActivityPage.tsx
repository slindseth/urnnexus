import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type SVGProps } from "react";
import { AppHeader } from "../components/Layout";
import { EmptyState } from "../components/EmptyState";
import { StatusPill } from "../components/StatusPill";
import { formatDateTime, formatTimeOfDay } from "../lib/api";
import { useActivityData } from "../lib/useActivityData";
import type { ActivityError, ActivityEvent, ActivityLevel, ActivityLogEntry, ActivityState } from "../types";

const STATUS_TONES: Record<ActivityState, "success" | "info" | "warning" | "danger" | "neutral"> = {
  Klar: "success",
  Starter: "info",
  Synkroniserer: "info",
  Analyserer: "info",
  "Genererer rapport": "warning",
  "Sender e-post": "warning",
  Feilet: "danger",
};

const LEVEL_TONES: Record<ActivityLevel, "success" | "info" | "warning" | "danger" | "neutral"> = {
  INFO: "info",
  SUCCESS: "success",
  WARNING: "warning",
  ERROR: "danger",
};

const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function ActivityPage() {
  const { status, statusLoading, statusError, events, eventsLoading, eventsError, logs, logsLoading, logsError } = useActivityData();
  const [searchTerm, setSearchTerm] = useState("");
  const [pinLogsToTop, setPinLogsToTop] = useState(true);
  const [clearedAfterMs, setClearedAfterMs] = useState(0);
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");
  const logViewportRef = useRef<HTMLDivElement | null>(null);

  const visibleEvents = sortActivityEntries(events?.events ?? []);
  const visibleErrors = sortActivityEntries(events?.errors ?? []);
  const visibleLogs = useMemo(() => {
    const normalizedSearchTerm = searchTerm.trim().toLowerCase();
    const filteredLogs = (logs?.entries ?? []).filter((entry) => {
      const timestampMs = Date.parse(entry.timestamp);
      if (Number.isFinite(timestampMs) && timestampMs <= clearedAfterMs) {
        return false;
      }
      if (!normalizedSearchTerm) {
        return true;
      }
      const haystack = [entry.message, entry.project_name, entry.component, entry.level, formatTimeOfDay(entry.timestamp)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedSearchTerm);
    });
    return sortActivityEntries(filteredLogs);
  }, [clearedAfterMs, logs?.entries, searchTerm]);

  useIsomorphicLayoutEffect(() => {
    if (!pinLogsToTop) {
      return;
    }
    const container = logViewportRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = 0;
  }, [events?.errors, events?.events, events?.updated_at, logs?.updated_at, pinLogsToTop, visibleLogs]);

  useEffect(() => {
    if (copyState !== "copied") {
      return undefined;
    }
    const timeout = window.setTimeout(() => setCopyState("idle"), 1600);
    return () => window.clearTimeout(timeout);
  }, [copyState]);

  async function handleCopyLogs() {
    const text = buildLogExport(visibleLogs);
    if (!text) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("copied");
    } catch {
      setCopyState("idle");
    }
  }

  function handleDownloadLogs() {
    const text = buildLogExport(visibleLogs);
    if (!text) {
      return;
    }
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `urn-nexus-aktivitet-${new Date().toISOString().replace(/[:.]/g, "-")}.log`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function handleClearLogs() {
    setClearedAfterMs(Date.now());
  }

  function handleLogScroll() {
    const container = logViewportRef.current;
    if (!container) {
      return;
    }
    const isAtTop = container.scrollTop <= 1;
    setPinLogsToTop(isAtTop);
  }

  const statusTone = status ? STATUS_TONES[status.state] : "neutral";
  const updatedAt = status?.updated_at ?? events?.updated_at ?? logs?.updated_at ?? null;
  const logSearchPlaceholder = logsLoading ? "Laster logger ..." : "Søk i logg";

  return (
    <div className="page-stack activity-page">
      <AppHeader title="Aktivitet" description="Siste hendelser, systemstatus og live aktivitet." />

      <section className="activity-grid" aria-label="Operasjonsstatus">
        <ActivityPanel
          title="Systemstatus"
          icon={<PulseIcon />}
          note={updatedAt ? `Oppdatert ${formatDateTime(updatedAt)}` : "Laster status ..."}
          className="activity-panel--status"
        >
          {statusError && !status ? (
            <EmptyState title="Kunne ikke hente systemstatus" description={statusError} />
          ) : statusLoading && !status ? (
            <div className="loading-copy">Laster systemstatus ...</div>
          ) : status ? (
            <div className="activity-status">
              <div className="activity-status__topline">
                <StatusPill status={status.state} label={status.state} tone={statusTone} />
                <span className="activity-status__uptime">Oppetid {status.uptime}</span>
              </div>
              <dl className="activity-status__grid">
                <StatusDefinition label="Prosjekt" value={status.project_name ?? "Alle prosjekter"} />
                <StatusDefinition label="Aktivitet" value={status.activity ?? "Ingen aktiv jobb"} />
                <StatusDefinition label="Status" value={status.status ?? "Ingen aktiv jobb"} />
                <StatusDefinition label="Appliance" value={status.appliance_available ? "Tilgjengelig" : "Utilgjengelig"} />
              </dl>
              <div className="activity-status__meta">
                <span>Backend {status.backend_version ?? "—"}</span>
                <span>Uptime {status.uptime}</span>
              </div>
            </div>
          ) : (
            <EmptyState title="Ingen status ennå" description="Det finnes ingen systemstatus å vise akkurat nå." />
          )}
        </ActivityPanel>

        <ActivityPanel
          title="Siste hendelser"
          icon={<FeedIcon />}
          note={visibleEvents.length > 0 ? `${visibleEvents.length.toLocaleString("nb-NO")} hendelser` : "Ingen hendelser ennå"}
          className="activity-panel--feed"
        >
          {eventsError && visibleEvents.length === 0 ? (
            <EmptyState title="Kunne ikke hente hendelser" description={eventsError} />
          ) : eventsLoading && visibleEvents.length === 0 ? (
            <div className="loading-copy">Laster hendelser ...</div>
          ) : visibleEvents.length > 0 ? (
            <ol className="activity-feed">
              {visibleEvents.map((event) => (
                <ActivityFeedRow key={`${event.timestamp}:${event.level}:${event.message}`} entry={event} />
              ))}
            </ol>
          ) : (
            <EmptyState title="Ingen hendelser ennå" description="Når Nexus jobber, vil de viktigste operasjonene vises her." />
          )}
        </ActivityPanel>

        <ActivityPanel
          title="Feilmeldinger"
          icon={<AlertIcon />}
          note={visibleErrors.length > 0 ? `${visibleErrors.length.toLocaleString("nb-NO")} aktive feil` : "Ingen aktive feil"}
          className="activity-panel--errors"
        >
          {eventsError && visibleErrors.length === 0 ? (
            <EmptyState title="Kunne ikke hente feilmeldinger" description={eventsError} />
          ) : eventsLoading && visibleErrors.length === 0 ? (
            <div className="loading-copy">Laster feilmeldinger ...</div>
          ) : visibleErrors.length > 0 ? (
            <ol className="activity-error-list">
              {visibleErrors.map((error) => (
                <ActivityErrorRow key={`${error.timestamp}:${error.message}`} entry={error} />
              ))}
            </ol>
          ) : (
            <EmptyState title="Ingen aktive feil" description="Ingen feilsignaler krever oppmerksomhet akkurat nå." />
          )}
        </ActivityPanel>
      </section>

      <section className="surface surface--padded activity-log-panel" aria-label="Live logg">
        <div className="section-head">
          <div>
            <div className="section-kicker">Live</div>
            <h2 className="section-title">Live logg</h2>
          </div>
          <div className="section-head__actions">
            <div className="section-head__note">
              {logs?.entries.length ? `${visibleLogs.length.toLocaleString("nb-NO")} av ${logs.entries.length.toLocaleString("nb-NO")} linjer` : "Oppdateres hvert 4. sekund"}
            </div>
            <label className="field field--inline activity-log-search">
              <span>Søk</span>
              <input value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} placeholder={logSearchPlaceholder} />
            </label>
            <button type="button" className="button button--secondary" onClick={handleClearLogs}>
              Tøm visning
            </button>
            <button type="button" className="button button--subtle" onClick={() => void handleCopyLogs()} disabled={visibleLogs.length === 0}>
              {copyState === "copied" ? "Kopiert" : "Kopier"}
            </button>
            <button type="button" className="button button--subtle" onClick={handleDownloadLogs} disabled={visibleLogs.length === 0}>
              Last ned logg
            </button>
          </div>
        </div>

        {logsError && !logs ? <EmptyState title="Kunne ikke hente logg" description={logsError} /> : null}

        <div ref={logViewportRef} className="activity-log-viewport" onScroll={handleLogScroll}>
          {logsLoading && visibleLogs.length === 0 ? (
            <div className="loading-copy">Laster logg ...</div>
          ) : visibleLogs.length > 0 ? (
            <div className="activity-log-list">
              {visibleLogs.map((entry) => (
                <ActivityLogRow key={`${entry.timestamp}:${entry.level}:${entry.message}`} entry={entry} />
              ))}
            </div>
          ) : (
            <EmptyState
              title="Ingen logglinjer"
              description={
                searchTerm.trim()
                  ? "Søket fant ingen logglinjer i den nyligste tailen."
                  : "Logglinjer vises her når Nexus og appliance produserer aktivitet."
              }
            />
          )}
        </div>
      </section>
    </div>
  );
}

type TimestampedActivity = { timestamp: string };

function sortActivityEntries<T extends TimestampedActivity>(entries: T[]): T[] {
  return [...entries].sort((left, right) => {
    const leftTimestamp = Date.parse(left.timestamp);
    const rightTimestamp = Date.parse(right.timestamp);

    if (Number.isFinite(leftTimestamp) && Number.isFinite(rightTimestamp)) {
      return rightTimestamp - leftTimestamp;
    }
    if (Number.isFinite(rightTimestamp)) {
      return 1;
    }
    if (Number.isFinite(leftTimestamp)) {
      return -1;
    }
    return right.timestamp.localeCompare(left.timestamp);
  });
}

function ActivityPanel({
  title,
  icon,
  note,
  children,
  className = "",
}: {
  title: string;
  icon: ReactNode;
  note: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <article className={`activity-panel ${className}`.trim()}>
      <div className="activity-panel__head">
        <div className="activity-panel__title-wrap">
          <span className="activity-panel__icon" aria-hidden="true">
            {icon}
          </span>
          <h2 className="activity-panel__title">{title}</h2>
        </div>
        <div className="activity-panel__note">{note}</div>
      </div>
      <div className="activity-panel__body">{children}</div>
    </article>
  );
}

function StatusDefinition({ label, value }: { label: string; value: string }) {
  return (
    <div className="activity-status__item">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function ActivityFeedRow({ entry }: { entry: ActivityEvent }) {
  return (
    <li className="activity-feed__item">
      <div className="activity-feed__meta">
        <span className="activity-feed__time">{formatTimeOfDay(entry.timestamp)}</span>
        <StatusPill status={entry.level} label={entry.level} tone={LEVEL_TONES[entry.level]} />
      </div>
      <div className="activity-feed__message">{entry.message}</div>
      {entry.project_name || entry.component ? (
        <div className="activity-feed__subline">
          {[entry.project_name, entry.component].filter(Boolean).join(" · ")}
        </div>
      ) : null}
    </li>
  );
}

function ActivityErrorRow({ entry }: { entry: ActivityError }) {
  return (
    <li className="activity-error-list__item">
      <div className="activity-error-list__meta">
        <span className="activity-error-list__time">{formatTimeOfDay(entry.timestamp)}</span>
        {entry.project_name ? <span className="activity-error-list__project">{entry.project_name}</span> : <span className="activity-error-list__project">—</span>}
      </div>
      <div className="activity-error-list__message">{entry.message}</div>
      {entry.component ? <div className="activity-error-list__component">{entry.component}</div> : null}
    </li>
  );
}

function ActivityLogRow({ entry }: { entry: ActivityLogEntry }) {
  return (
    <div className={`activity-log-row activity-log-row--${entry.level.toLowerCase()}`}>
      <span className="activity-log-row__time">{formatTimeOfDay(entry.timestamp)}</span>
      <StatusPill status={entry.level} label={entry.level} tone={LEVEL_TONES[entry.level]} />
      <span className="activity-log-row__message">{entry.message}</span>
      {entry.project_name || entry.component ? (
        <span className="activity-log-row__meta">{[entry.project_name, entry.component].filter(Boolean).join(" · ")}</span>
      ) : null}
    </div>
  );
}

function buildLogExport(entries: ActivityLogEntry[]): string {
  return entries
    .map((entry) => {
      const meta = [entry.project_name, entry.component].filter(Boolean).join(" · ");
      return [formatTimeOfDay(entry.timestamp), entry.level, meta ? `${entry.message} (${meta})` : entry.message].join(" ");
    })
    .join("\n");
}

function PulseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M1.8 8h2.8l1.2-2.5 1.6 5 1.4-3h3.4" />
      <circle cx="8" cy="8" r="5.5" />
    </svg>
  );
}

function FeedIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M2.5 4.5h11" />
      <path d="M2.5 8h11" />
      <path d="M2.5 11.5h7.5" />
      <circle cx="11.8" cy="11.5" r=".8" fill="currentColor" stroke="none" />
    </svg>
  );
}

function AlertIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M8 2.4 14 13H2z" />
      <path d="M8 6v3.2" />
      <path d="M8 11.3h.01" />
    </svg>
  );
}
