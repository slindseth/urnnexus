import { projectUrl } from "./api";
import type { ProjectSummary } from "../types";

export const showSampleProjectsInUi = import.meta.env.VITE_SHOW_SAMPLE_PROJECTS === "true";

export type ProjectStatusLevel = "PENDING" | "RUNNING" | "SUCCESS" | "SUCCESS_WITH_WARNINGS" | "FAILED" | "NO_REPORT" | "PARTIAL" | "STALE" | "CANCELLED";

export type StatusTone = "neutral" | "success" | "warning" | "danger" | "info";

export interface ProjectStatusMeta {
  level: ProjectStatusLevel;
  label: string;
  tone: StatusTone;
  description: string;
}

export interface ProjectIssue {
  kind: "warning" | "error";
  message: string;
  technicalDetails: string[];
}

export interface ProjectViewModel {
  raw: ProjectSummary;
  projectName: string;
  displayName: string;
  sourceLabel: string;
  isLocalCacheOnly: boolean;
  breadcrumbPath: string;
  projectHref: string;
  filesHref: string;
  reportsHref: string;
  isSampleProject: boolean;
  fileCount: number;
  fileCountLabel: string;
  reportCount: number;
  reportCountLabel: string;
  commentDocumentCount: number;
  latestReport: {
    name: string;
    openUrl: string | null;
    createdAt: string | null;
    modifiedAt: string | null;
  } | null;
  latestReportLabel: string;
  lastSyncedAt: string | null;
  lastAnalyzedAt: string | null;
  activityTimestamp: string | null;
  status: ProjectStatusMeta;
  warnings: ProjectIssue[];
  errors: ProjectIssue[];
  issues: ProjectIssue[];
  technicalWarnings: string[];
  technicalErrors: string[];
  hasWarnings: boolean;
  hasErrors: boolean;
  hasCommentOnlyFiles: boolean;
}

const STATUS_META: Record<ProjectStatusLevel, ProjectStatusMeta> = {
  PARTIAL: { level: "PARTIAL", label: "Delvis gjennomgått", tone: "warning", description: "Gjennomgangen har gjenstående kontroll eller begrensninger." },
  STALE: { level: "STALE", label: "Utdatert snapshot", tone: "warning", description: "Resultatet gjelder et tidligere kildegrunnlag." },
  CANCELLED: { level: "CANCELLED", label: "Stoppet", tone: "warning", description: "Gjennomgangen er stoppet. Lagret arbeid er beholdt." },
  PENDING: {
    level: "PENDING",
    label: "Venter",
    tone: "info",
    description: "Prosjektet er synket, men analyse er ikke kjørt.",
  },
  RUNNING: {
    level: "RUNNING",
    label: "Analyse pågår",
    tone: "info",
    description: "Analyse kjører nå.",
  },
  SUCCESS: {
    level: "SUCCESS",
    label: "Fullført",
    tone: "success",
    description: "Analyse er fullført uten varsler.",
  },
  SUCCESS_WITH_WARNINGS: {
    level: "SUCCESS_WITH_WARNINGS",
    label: "Fullført med varsler",
    tone: "warning",
    description: "Analyse er fullført, men portalen har registrert varsler.",
  },
  FAILED: {
    level: "FAILED",
    label: "Feilet",
    tone: "danger",
    description: "Analyse feilet.",
  },
  NO_REPORT: {
    level: "NO_REPORT",
    label: "Ingen rapport",
    tone: "neutral",
    description: "Prosjektet er synket, men ingen rapport finnes.",
  },
};

export function isSampleProject(project: ProjectSummary): boolean {
  return project.is_sample_project;
}

export function displaySourceLabel(project: ProjectSummary): string {
  if (project.is_sample_project) {
    return "Demo/lokal sample";
  }
  return project.source_label;
}

export function isLocalCacheOnlyProject(project: ProjectSummary): boolean {
  return Boolean(project.is_local_cache_only) || project.source_label.trim().toLowerCase() === "kun lokal cache";
}

export function filterVisibleProjects(
  projects: ProjectSummary[],
  includeSampleProjects = showSampleProjectsInUi,
  includeLocalCacheOnlyProjects = false,
): ProjectSummary[] {
  return projects.filter((project) => {
    if (!includeSampleProjects && isSampleProject(project)) {
      return false;
    }
    if (!includeLocalCacheOnlyProjects && isLocalCacheOnlyProject(project)) {
      return false;
    }
    return true;
  });
}

export function projectActivityTimestamp(project: ProjectSummary): string | null {
  return project.latest_comment_created_at ?? project.last_synced_at ?? project.latest_comment_modified_at ?? project.last_analyzed_at;
}

export function displayProjectPath(relativeProjectPath: string): string {
  const prefix = "AnbudAppliance/";
  return relativeProjectPath.startsWith(prefix) ? relativeProjectPath.slice(prefix.length) : relativeProjectPath;
}

function rawStatus(value: string | null | undefined): string {
  return String(value ?? "").trim().toLowerCase();
}

function statusLevelForProject(project: ProjectSummary, issues: ProjectIssue[]): ProjectStatusLevel {
  const status = rawStatus(project.status);
  const reportCount = Math.max(project.report_count, project.comment_document_count);
  if (status === "partial") return "PARTIAL";
  if (status === "stale") return "STALE";
  if (status === "cancelled") return "CANCELLED";

  if (["failed", "failure", "error", "errored"].includes(status)) {
    return "FAILED";
  }
  if (["running", "in_progress", "processing", "analyzing", "analysing"].includes(status)) {
    return "RUNNING";
  }
  if (["pending", "queued", "not_started"].includes(status)) {
    return "PENDING";
  }
  if (reportCount <= 0) {
    return "NO_REPORT";
  }
  if (["completed_with_warnings", "success_with_warnings", "warning", "warnings"].includes(status)) {
    return "SUCCESS_WITH_WARNINGS";
  }
  if (issues.some((issue) => issue.kind === "warning" || issue.kind === "error")) {
    return "SUCCESS_WITH_WARNINGS";
  }
  if (["completed", "success", "ok", "skipped_no_changes", "unknown", ""].includes(status)) {
    return "SUCCESS";
  }
  return "SUCCESS";
}

export function projectStatusMeta(level: ProjectStatusLevel): ProjectStatusMeta {
  return STATUS_META[level];
}

function translateTechnicalIssue(message: string): string {
  const text = message.trim();
  const lowered = text.toLowerCase();

  if (lowered.includes("project root is missing")) {
    return "Lokal cache mangler prosjektmappe.";
  }
  if (lowered.includes("referenced report path is missing")) {
    return "Rapport finnes i OneDrive men lokal kopi er ikke tilgjengelig.";
  }
  if (lowered.includes("remote report url recorded")) {
    return "Rapport finnes kun som ekstern URL.";
  }
  if (lowered.includes("unable to inspect one of the comment documents")) {
    return "En rapport i Kommentarer kunne ikke leses fra lokal cache.";
  }
  if (lowered.includes("unable to inspect file")) {
    return "En fil i lokal cache kunne ikke leses.";
  }
  if (lowered.includes("onedrive sync state cache")) {
    return "OneDrive sync-state kan ikke leses fra lokal cache.";
  }
  if (lowered.includes("no source files were found in the local appliance cache")) {
    return "Ingen kildefiler er funnet i lokal cache.";
  }
  if (lowered.includes("only generated comment documents") || lowered.includes("only comment documents were found")) {
    return "Prosjektet har kommentardokumenter, men ingen kildefiler i lokal cache.";
  }
  if (lowered.includes("kommentarer folders are excluded")) {
    return "Kommentardokumenter holdes utenfor filantallet.";
  }
  if (lowered.includes("symlinks are excluded")) {
    return "Lenkede filer holdes utenfor filantallet.";
  }
  if (lowered.includes("files outside the resolved project root")) {
    return "Filer utenfor prosjektmappen holdes utenfor filantallet.";
  }
  if (lowered.includes("unreadable files are excluded")) {
    return "Noen filer kunne ikke leses fra lokal cache.";
  }

  return text;
}

function buildIssues(messages: string[], kind: ProjectIssue["kind"]): ProjectIssue[] {
  const grouped = new Map<string, ProjectIssue>();
  for (const message of messages) {
    const technical = message.trim();
    if (!technical) {
      continue;
    }
    const translated = translateTechnicalIssue(technical);
    const key = `${kind}:${translated}`;
    const existing = grouped.get(key);
    if (existing) {
      if (!existing.technicalDetails.includes(technical)) {
        existing.technicalDetails.push(technical);
      }
      continue;
    }
    grouped.set(key, {
      kind,
      message: translated,
      technicalDetails: [technical],
    });
  }
  return [...grouped.values()];
}

function shouldHideCacheOnlyIssue(project: ProjectSummary, issue: ProjectIssue, reportCount: number): boolean {
  const details = issue.technicalDetails.join(" ").toLowerCase();
  const hasAccessibleReport = reportCount > 0 && Boolean(project.latest_comment_document_open_url);
  const hasUsefulProjectContent = project.file_count > 0 || hasAccessibleReport;

  if (details.includes("project root is missing") && hasUsefulProjectContent) {
    return true;
  }
  if (details.includes("referenced report path is missing") && hasAccessibleReport) {
    return true;
  }
  if (details.includes("remote report url recorded") && hasAccessibleReport) {
    return true;
  }
  return false;
}

function countLabel(count: number, singular: string, plural: string): string {
  return `${count.toLocaleString("nb-NO")} ${count === 1 ? singular : plural}`;
}

function latestReportLabel(project: ProjectSummary): string {
  if (!project.latest_comment_document) {
    return "Ingen rapport";
  }
  return project.latest_comment_document;
}

function fileCountLabel(project: ProjectSummary): string {
  if (project.file_count === 0 && project.comment_document_count > 0) {
    return "0 filer - kun kommentardokumenter";
  }
  return countLabel(project.file_count, "fil", "filer");
}

export function createProjectViewModel(project: ProjectSummary): ProjectViewModel {
  const breadcrumbPath = displayProjectPath(project.relative_project_path);
  const reportCount = Math.max(project.report_count, project.comment_document_count);
  const rawWarnings = buildIssues(project.warnings, "warning");
  const rawErrors = buildIssues(project.errors, "error");
  const warnings = rawWarnings.filter((issue) => !shouldHideCacheOnlyIssue(project, issue, reportCount));
  const errors = rawErrors.filter((issue) => !shouldHideCacheOnlyIssue(project, issue, reportCount));
  const status = projectStatusMeta(statusLevelForProject(project, [...warnings, ...errors]));
  if (status.level === "SUCCESS_WITH_WARNINGS" && warnings.length === 0 && errors.length === 0 && rawWarnings.length === 0 && rawErrors.length === 0) {
    warnings.push({
      kind: "warning",
      message: "Varsler registrert i analysen.",
      technicalDetails: [`API-status: ${project.status}`],
    });
  }
  const issues = [...warnings, ...errors];

  return {
    raw: project,
    projectName: project.project_name,
    displayName: project.display_name,
    sourceLabel: displaySourceLabel(project),
    isLocalCacheOnly: isLocalCacheOnlyProject(project),
    breadcrumbPath,
    projectHref: projectUrl(project.project_name),
    filesHref: projectUrl(project.project_name, "files"),
    reportsHref: projectUrl(project.project_name, "reports"),
    isSampleProject: project.is_sample_project,
    fileCount: project.file_count,
    fileCountLabel: fileCountLabel(project),
    reportCount,
    reportCountLabel: countLabel(reportCount, "rapport", "rapporter"),
    commentDocumentCount: project.comment_document_count,
    latestReport: project.latest_comment_document
      ? {
          name: project.latest_comment_document,
          openUrl: project.latest_comment_document_open_url,
          createdAt: project.latest_comment_created_at,
          modifiedAt: project.latest_comment_modified_at,
        }
      : null,
    latestReportLabel: latestReportLabel(project),
    lastSyncedAt: project.last_synced_at,
    lastAnalyzedAt: project.last_analyzed_at,
    activityTimestamp: projectActivityTimestamp(project),
    status,
    warnings,
    errors,
    issues,
    technicalWarnings: project.warnings,
    technicalErrors: project.errors,
    hasWarnings: warnings.length > 0 || status.level === "SUCCESS_WITH_WARNINGS",
    hasErrors: errors.length > 0 || status.level === "FAILED",
    hasCommentOnlyFiles: project.file_count === 0 && project.comment_document_count > 0,
  };
}

export function createProjectViewModels(projects: ProjectSummary[]): ProjectViewModel[] {
  return projects.map(createProjectViewModel);
}

export function sortProjectsByActivity<T extends ProjectSummary | ProjectViewModel>(projects: T[]): T[] {
  return [...projects].sort((left, right) => {
    const leftTimestamp = "activityTimestamp" in left ? left.activityTimestamp : projectActivityTimestamp(left);
    const rightTimestamp = "activityTimestamp" in right ? right.activityTimestamp : projectActivityTimestamp(right);
    const leftTime = leftTimestamp ? Date.parse(leftTimestamp) : 0;
    const rightTime = rightTimestamp ? Date.parse(rightTimestamp) : 0;
    if (rightTime !== leftTime) {
      return rightTime - leftTime;
    }
    const leftName = "displayName" in left ? left.displayName : left.display_name;
    const rightName = "displayName" in right ? right.displayName : right.display_name;
    return leftName.localeCompare(rightName, "nb");
  });
}
