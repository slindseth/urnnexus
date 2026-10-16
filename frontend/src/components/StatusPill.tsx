import { projectStatusMeta, type ProjectStatusLevel, type StatusTone } from "../lib/projects";

interface StatusBadgeProps {
  status: string;
  label?: string;
  tone?: StatusTone;
}

export function StatusPill({ status, label, tone }: StatusBadgeProps) {
  return <StatusBadge status={status} label={label} tone={tone} />;
}

export function StatusBadge({ status, label, tone }: StatusBadgeProps) {
  const resolvedTone = tone ?? toneForStatus(status);
  return (
    <span className={`status-badge status-badge--${resolvedTone}`}>
      <span className="status-badge__dot" aria-hidden="true" />
      <span className="status-badge__label">{label ?? humanizeStatus(status)}</span>
    </span>
  );
}

function humanizeStatus(status: string): string {
  if (isProjectStatusLevel(status)) {
    return projectStatusMeta(status).label;
  }
  const lowered = status.toLowerCase();
  if (lowered === "partial") return "Delvis gjennomgått";
  if (lowered === "stale") return "Utdatert snapshot";
  if (lowered === "cancelled") return "Stoppet";
  if (lowered === "online") {
    return "Online";
  }
  if (lowered === "offline") {
    return "Offline";
  }
  if (lowered === "loading") {
    return "Laster";
  }
  if (lowered === "latest") {
    return "Nyeste";
  }
  if (lowered === "archived") {
    return "Arkiv";
  }
  if (lowered === "configured") {
    return "Konfigurert";
  }
  if (lowered === "not_configured") {
    return "Mangler config";
  }
  if (lowered === "available") {
    return "Tilgjengelig";
  }
  if (lowered === "unavailable") {
    return "Utilgjengelig";
  }
  if (lowered === "warning") {
    return "Varsel";
  }
  if (lowered === "failed") {
    return "Feilet";
  }
  return status.replaceAll("_", " ");
}

function toneForStatus(status: string): StatusBadgeProps["tone"] {
  if (isProjectStatusLevel(status)) {
    return projectStatusMeta(status).tone;
  }
  const lowered = status.toLowerCase();
  if (["partial", "stale", "cancelled"].includes(lowered)) return "warning";
  if (lowered.includes("warning")) {
    return "warning";
  }
  if (lowered.includes("failed") || lowered.includes("error")) {
    return "danger";
  }
  if (lowered.includes("not_configured") || lowered.includes("unavailable")) {
    return "warning";
  }
  if (lowered.includes("completed") || lowered.includes("online") || lowered.includes("available") || lowered.includes("configured")) {
    return "success";
  }
  if (lowered.includes("skipped") || lowered.includes("loading")) {
    return "info";
  }
  return "neutral";
}

function isProjectStatusLevel(status: string): status is ProjectStatusLevel {
  return ["PENDING", "RUNNING", "SUCCESS", "SUCCESS_WITH_WARNINGS", "FAILED", "NO_REPORT", "PARTIAL", "STALE", "CANCELLED"].includes(status);
}
