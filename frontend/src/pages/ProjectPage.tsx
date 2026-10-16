import { useOutletContext, useParams, useLocation, Outlet, Link } from "react-router-dom";
import { ErrorState } from "../components/ErrorState";
import { ProjectHeader } from "../components/Layout";
import { Tabs } from "../components/Tabs";
import { formatDateTime, getProject, projectUrl, safeDecodeProjectName } from "../lib/api";
import { createProjectViewModel, type ProjectViewModel } from "../lib/projects";
import { useResource } from "../lib/useResource";
import type { ProjectDetailResponse } from "../types";

export interface ProjectPageContext {
  project: ProjectViewModel;
  projectDetail: ProjectDetailResponse;
  reloadProject: () => void;
}

export function useProjectPageContext(): ProjectPageContext {
  return useOutletContext<ProjectPageContext>();
}

function formatLatestReport(project: ProjectViewModel): string {
  if (project.latestReport === null) {
    return "Ingen rapport";
  }
  const timestamp = project.latestReport.createdAt;
  if (timestamp === null) {
    return project.latestReport.name;
  }
  return `${project.latestReport.name} · ${formatDateTime(timestamp)}`;
}

export function ProjectPage() {
  const { projectName: routeProjectName = "" } = useParams();
  const projectName = safeDecodeProjectName(routeProjectName);
  const selectedJob = new URLSearchParams(useLocation().search).get("job");
  const { data: project, loading, error, reload } = useResource(() => getProject(projectName), [projectName]);

  const tabs = projectName
    ? [
        { to: projectUrl(projectName), label: "Oversikt" },
        { to: projectUrl(projectName, "review"), label: "Funn og kilder" },
        { to: projectUrl(projectName, "files"), label: "Filer" },
        { to: projectUrl(projectName, "reports"), label: "Rapporter" },
      ].map((tab) => ({ ...tab, to: tab.to + (selectedJob ? `?job=${encodeURIComponent(selectedJob)}` : "") }))
    : [];

  return (
    <div className="page-stack">
      {error ? (
        <ErrorState
          title="Kunne ikke åpne prosjektet"
          description={error}
          action={
            <Link className="button button--secondary" to="/projects">
              Tilbake til prosjekter
            </Link>
          }
        />
      ) : loading ? (
        <section className="surface surface--padded">
          <div className="loading-copy">Laster prosjekt …</div>
        </section>
      ) : !project ? (
        <ErrorState
          title="Kunne ikke åpne prosjektet"
          description="API-et returnerte ikke prosjektdata."
          action={
            <Link className="button button--secondary" to="/projects">
              Tilbake til prosjekter
            </Link>
          }
        />
      ) : (
        <ProjectContent projectDetail={project} reload={reload} tabs={tabs} />
      )}
    </div>
  );
}

function ProjectContent({
  projectDetail,
  reload,
  tabs,
}: {
  projectDetail: ProjectDetailResponse;
  reload: () => void;
  tabs: Array<{ to: string; label: string }>;
}) {
  const project = createProjectViewModel(projectDetail);

  return (
    <>
      <ProjectHeader
        title={project.displayName}
        breadcrumbPath={project.breadcrumbPath}
        sourceLabel={project.sourceLabel}
        status={project.status.level}
        meta={[
          project.fileCountLabel,
          project.reportCountLabel,
          formatLatestReport(project),
          project.lastSyncedAt ? `Sist synket ${formatDateTime(project.lastSyncedAt)}` : "Sist synket: ukjent",
        ]}
        actions={
          <button type="button" className="button button--secondary" onClick={reload}>
            Oppdater visning
          </button>
        }
      />
      <Tabs items={tabs} />
      <Outlet context={{ project, projectDetail, reloadProject: reload }} />
    </>
  );
}
