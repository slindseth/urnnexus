import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/Layout";
import { ErrorState } from "../components/ErrorState";
import { ProjectTable } from "../components/ProjectTable";
import { useAppData } from "../context/AppDataContext";
import { ApiRequestError, createProject, deleteProject, getUserFacingErrorMessage, projectUrl } from "../lib/api";
import type { ProjectViewModel } from "../lib/projects";

export function ProjectsPage() {
  const navigate = useNavigate();
  const { projects, projectsLoading, projectsError, health, healthLoading, refresh, removeProjectByName } = useAppData();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [createMessage, setCreateMessage] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState<ProjectViewModel | null>(null);
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const isInitialProjectsLoad = projectsLoading && projects.length === 0;
  const graphWriteReady = health?.graph_write_status === "configured";
  const createDisabledReason = healthLoading
    ? "Kontrollerer Microsoft Graph-write ..."
    : graphWriteReady
      ? null
      : (health?.graph_write_detail ?? "Microsoft Graph-write er ikke konfigurert.");

  useEffect(() => {
    if (!toastMessage) {
      return;
    }
    const timeout = window.setTimeout(() => setToastMessage(null), 3600);
    return () => window.clearTimeout(timeout);
  }, [toastMessage]);

  async function handleCreateProject() {
    if (!newProjectName.trim() || isCreating) {
      return;
    }
    setIsCreating(true);
    setCreateMessage("Oppretter prosjekt direkte i OneDrive og synker Nexus ...");
    try {
      const response = await createProject({ project_name: newProjectName });
      setCreateMessage(response.warning ?? `${response.project_name} ble opprettet i OneDrive.`);
      setNewProjectName("");
      setIsCreateOpen(false);
      refresh();
      navigate(projectUrl(response.project_name));
    } catch (error) {
      setCreateMessage(getUserFacingErrorMessage(error, "Kunne ikke opprette prosjektet."));
    } finally {
      setIsCreating(false);
    }
  }

  async function handleDeleteProject() {
    if (!projectToDelete || isDeleting) {
      return;
    }
    setIsDeleting(true);
    setDeleteMessage(null);
    try {
      const response = await deleteProject(projectToDelete.projectName);
      removeProjectByName(projectToDelete.projectName);
      setDeleteMessage(null);
      setToastMessage(response.message);
      setProjectToDelete(null);
      void refresh();
    } catch (error) {
      if (projectToDelete && isDeleteProjectMissingError(error, projectToDelete)) {
        removeProjectByName(projectToDelete.projectName);
        setDeleteMessage(null);
        setToastMessage("Prosjektet finnes ikke lenger i OneDrive.");
        setProjectToDelete(null);
        void refresh();
        return;
      }
      setDeleteMessage(getUserFacingErrorMessage(error, "Kunne ikke slette prosjektet i OneDrive."));
    } finally {
      setIsDeleting(false);
    }
  }

  if (projectsError) {
    return <ErrorState title="Kunne ikke laste prosjektlisten" description={projectsError} />;
  }

  return (
    <div className="page-stack">
      <AppHeader
        title="Prosjekter"
        description=" "
      />

      {toastMessage ? <ProjectToast message={toastMessage} /> : null}

      <section className="surface surface--padded">
        <div className="section-head">
          <div>
            <div className="section-kicker"> </div>
            <h2 className="section-title">{projects.length.toLocaleString("nb-NO")} prosjekter</h2>
          </div>
          <div className="section-head__actions">
            <div className="section-head__note">{projectsLoading ? "Laster …" : " "}</div>
            <button
              type="button"
              className="button"
              onClick={() => setIsCreateOpen(true)}
              disabled={Boolean(createDisabledReason)}
              title={createDisabledReason ?? "Opprett prosjekt i OneDrive"}
            >
              Nytt prosjekt
            </button>
          </div>
        </div>
        {createMessage ? <div className="inline-note">{createMessage}</div> : null}
        {deleteMessage ? <div className="inline-note">{deleteMessage}</div> : null}
        {createDisabledReason ? <div className="inline-note">{createDisabledReason}</div> : null}
        {isInitialProjectsLoad ? (
          <div className="loading-copy">Laster prosjekter …</div>
        ) : (
          <ProjectTable
            projects={projects}
            emptyLabel="Ingen prosjekter å vise."
            onDeleteProject={setProjectToDelete}
          />
        )}
      </section>

      {isCreateOpen ? (
        <div className="modal-backdrop" role="presentation">
          <section className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="create-project-title">
            <div className="section-head">
              <div>
                <div className="section-kicker"> </div>
                <h2 className="section-title" id="create-project-title">
                  Nytt prosjekt
                </h2>
              </div>
              <button type="button" className="button button--secondary" onClick={() => setIsCreateOpen(false)}>
                Lukk
              </button>
            </div>
            <label className="field">
              <span>Prosjektnavn</span>
              <input value={newProjectName} onChange={(event) => setNewProjectName(event.target.value)} autoFocus placeholder="Bryn Skole" />
            </label>
            <div className="modal-panel__actions">
              <button type="button" className="button button--secondary" onClick={() => setIsCreateOpen(false)}>
                Avbryt
              </button>
              <button type="button" className="button" onClick={() => void handleCreateProject()} disabled={isCreating || !newProjectName.trim()}>
                Opprett prosjekt
              </button>
            </div>
            <div className="inline-note">Prosjektet opprettes direkte i OneDrive og blir synlig etter Graph-respons og Nexus-sync.</div>
          </section>
        </div>
      ) : null}

      {projectToDelete ? (
        <DeleteProjectConfirmationDialog
          project={projectToDelete}
          isDeleting={isDeleting}
          onCancel={() => setProjectToDelete(null)}
          onConfirm={() => void handleDeleteProject()}
        />
      ) : null}
    </div>
  );
}

export function DeleteProjectConfirmationDialog({
  project,
  isDeleting,
  onCancel,
  onConfirm,
}: {
  project: ProjectViewModel;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="delete-project-title">
        <div className="section-head">
          <div>
            <div className="section-kicker">Prosjekt</div>
            <h2 className="section-title" id="delete-project-title">
              Slett prosjekt
            </h2>
          </div>
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={isDeleting}>
            Lukk
          </button>
        </div>
        <p className="modal-copy">Dette sletter prosjektet i OneDrive og fjerner det fra Nexus etter synk. Det sletter ikke lokal cache direkte.</p>
        <div className="project-table__name">{project.displayName}</div>
        <div className="modal-panel__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={isDeleting}>
            Avbryt
          </button>
          <button type="button" className="button button--danger" onClick={onConfirm} disabled={isDeleting}>
            Slett prosjekt
          </button>
        </div>
      </section>
    </div>
  );
}

function ProjectToast({ message }: { message: string }) {
  return (
    <div className="project-toast" role="status" aria-live="polite">
      {message}
    </div>
  );
}

function isDeleteProjectMissingError(error: unknown, project: ProjectViewModel): boolean {
  if (!(error instanceof ApiRequestError) || error.status !== 404) {
    return false;
  }
  const message = error.message.toLowerCase();
  const projectPath = project.raw.relative_project_path.toLowerCase();
  return message.includes(projectPath);
}
