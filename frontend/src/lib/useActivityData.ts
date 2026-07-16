import { useEffect, useState } from "react";
import { getActivityEvents, getActivityLogs, getActivityStatus, getSyncStatus } from "./api";
import type { ActivityEventsResponse, ActivityLogsResponse, ActivityStatusResponse, SyncStatusResponse } from "../types";

interface ActivityDataState {
  status: ActivityStatusResponse | null;
  statusLoading: boolean;
  statusError: string | null;
  syncStatus: SyncStatusResponse | null;
  events: ActivityEventsResponse | null;
  eventsLoading: boolean;
  eventsError: string | null;
  logs: ActivityLogsResponse | null;
  logsLoading: boolean;
  logsError: string | null;
  refresh: () => void;
}

const DEFAULT_REFRESH_INTERVAL_MS = 4000;

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export function useActivityData(refreshIntervalMs = DEFAULT_REFRESH_INTERVAL_MS): ActivityDataState {
  const [status, setStatus] = useState<ActivityStatusResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse | null>(null);
  const [events, setEvents] = useState<ActivityEventsResponse | null>(null);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [logs, setLogs] = useState<ActivityLogsResponse | null>(null);
  const [logsLoading, setLogsLoading] = useState(true);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timerId: number | undefined;

    async function loadActivityData() {
      const [statusResult, syncResult, eventsResult, logsResult] = await Promise.allSettled([getActivityStatus(), getSyncStatus(), getActivityEvents(), getActivityLogs()]);
      if (cancelled) {
        return;
      }

      if (statusResult.status === "fulfilled") {
        setStatus(statusResult.value);
        setStatusError(null);
      } else {
        setStatusError(errorMessage(statusResult.reason, "Kunne ikke lese aktivitetsstatus."));
      }

      if (syncResult.status === "fulfilled") {
        setSyncStatus(syncResult.value);
      }

      if (eventsResult.status === "fulfilled") {
        setEvents(eventsResult.value);
        setEventsError(null);
      } else {
        setEventsError(errorMessage(eventsResult.reason, "Kunne ikke lese hendelser."));
      }

      if (logsResult.status === "fulfilled") {
        setLogs(logsResult.value);
        setLogsError(null);
      } else {
        setLogsError(errorMessage(logsResult.reason, "Kunne ikke lese loggene."));
      }

      setStatusLoading(false);
      setEventsLoading(false);
      setLogsLoading(false);
      timerId = window.setTimeout(() => void loadActivityData(), refreshIntervalMs);
    }

    void loadActivityData();

    return () => {
      cancelled = true;
      if (timerId !== undefined) {
        window.clearTimeout(timerId);
      }
    };
  }, [refreshIndex, refreshIntervalMs]);

  return {
    status,
    statusLoading,
    statusError,
    syncStatus,
    events,
    eventsLoading,
    eventsError,
    logs,
    logsLoading,
    logsError,
    refresh: () => setRefreshIndex((value) => value + 1),
  };
}
