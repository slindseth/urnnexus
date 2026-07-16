// @vitest-environment jsdom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { useActivityData } from "./useActivityData";
import type { ActivityEventsResponse, ActivityLogsResponse, ActivityStatusResponse, SyncStatusResponse } from "../types";

let mountedRoot: Root | null = null;

function Probe({ onState }: { onState: (state: unknown) => void }) {
  const state = useActivityData(4000);

  useEffect(() => {
    onState(state);
  }, [onState, state]);

  return null;
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function makeStatus(updatedAt: string): ActivityStatusResponse {
  return {
    state: "Klar",
    activity: "Ingen aktiv jobb",
    status: "Ingen aktiv jobb",
    project_name: null,
    uptime: "01:23:41",
    uptime_seconds: 5021,
    backend_version: "0.1.9",
    appliance_available: true,
    last_synced_at: null,
    last_analyzed_at: null,
    updated_at: updatedAt,
  };
}

function makeEvents(updatedAt: string): ActivityEventsResponse {
  return {
    updated_at: updatedAt,
    events: [],
    errors: [],
  };
}

function makeLogs(updatedAt: string): ActivityLogsResponse {
  return {
    updated_at: updatedAt,
    entries: [],
  };
}

function makeSyncStatus(updatedAt: string): SyncStatusResponse {
  return {
    running: false,
    process_alive: false,
    lock_exists: false,
    lock_stale: false,
    activity: "idle",
    job_id: "sync-job",
    last_started_at: updatedAt,
    last_completed_at: updatedAt,
    last_error: null,
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
    status: "completed",
    job_type: "sync",
    run_mode: "sync_only",
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  act(() => {
    mountedRoot?.unmount();
  });
  mountedRoot = null;
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("useActivityData", () => {
  it("polls the activity endpoints on a repeating interval", async () => {
    vi.useFakeTimers();

    const statusSpy = vi
      .spyOn(api, "getActivityStatus")
      .mockResolvedValueOnce(makeStatus("2026-06-30T08:00:00+02:00"))
      .mockResolvedValue(makeStatus("2026-06-30T08:00:04+02:00"));
    const eventsSpy = vi
      .spyOn(api, "getActivityEvents")
      .mockResolvedValueOnce(makeEvents("2026-06-30T08:00:00+02:00"))
      .mockResolvedValue(makeEvents("2026-06-30T08:00:04+02:00"));
    const logsSpy = vi
      .spyOn(api, "getActivityLogs")
      .mockResolvedValueOnce(makeLogs("2026-06-30T08:00:00+02:00"))
      .mockResolvedValue(makeLogs("2026-06-30T08:00:04+02:00"));
    const syncStatusSpy = vi
      .spyOn(api, "getSyncStatus")
      .mockResolvedValueOnce(makeSyncStatus("2026-06-30T08:00:00+02:00"))
      .mockResolvedValue(makeSyncStatus("2026-06-30T08:00:04+02:00"));

    let latestState: unknown = null;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoot = root;

    act(() => {
      root.render(<Probe onState={(state) => (latestState = state)} />);
    });

    await flushEffects();

    expect(statusSpy).toHaveBeenCalledTimes(1);
    expect(eventsSpy).toHaveBeenCalledTimes(1);
    expect(logsSpy).toHaveBeenCalledTimes(1);
    expect(syncStatusSpy).toHaveBeenCalledTimes(1);
    expect((latestState as { status?: ActivityStatusResponse | null })?.status?.updated_at).toBe("2026-06-30T08:00:00+02:00");

    await act(async () => {
      vi.advanceTimersByTime(4000);
    });
    await flushEffects();

    expect(statusSpy).toHaveBeenCalledTimes(2);
    expect(eventsSpy).toHaveBeenCalledTimes(2);
    expect(logsSpy).toHaveBeenCalledTimes(2);
    expect(syncStatusSpy).toHaveBeenCalledTimes(2);
    expect((latestState as { status?: ActivityStatusResponse | null })?.status?.updated_at).toBe("2026-06-30T08:00:04+02:00");
  });
});
