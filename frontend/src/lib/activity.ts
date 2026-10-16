import type { ActivityEvidence } from "../types";

export type ActivityOriginFilter = "operational" | "test" | "unknown" | "all";

export function matchesOrigin(
  entry: ActivityEvidence,
  origin: ActivityOriginFilter,
): boolean {
  return origin === "all" || (entry.origin ?? "unknown") === origin;
}

export function activityKey(
  entry: ActivityEvidence & {
    timestamp: string | null;
    message: string;
    project_name: string | null;
    job_id?: string | null;
  },
): string {
  return (
    entry.event_id ??
    JSON.stringify([
      entry.timestamp,
      entry.job_id,
      entry.project_name,
      entry.message,
    ])
  );
}

export function formatActivityTimestamp(
  value: string | null | undefined,
): string {
  if (!value || !Number.isFinite(Date.parse(value)))
    return "Udatert · tidspunkt ukjent";
  return new Intl.DateTimeFormat("nb-NO", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(new Date(value));
}

export function sortActivityEntries<T extends { timestamp: string | null }>(
  entries: T[],
): T[] {
  const time = (value: string | null) =>
    value && Number.isFinite(Date.parse(value)) ? Date.parse(value) : -Infinity;
  return [...entries].sort((a, b) => time(b.timestamp) - time(a.timestamp));
}
