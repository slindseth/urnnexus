import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/Layout";
import { ErrorState } from "../components/ErrorState";
import { ProjectTable } from "../components/ProjectTable";
import { useAppData } from "../context/AppDataContext";
import { projectUrl } from "../lib/api";

export function AnalysisPage() {
  const { projects, projectsLoading, projectsError, refresh } = useAppData();
  const navigate = useNavigate();
  return (
    <div className="page-stack analysis-page">
      <AppHeader
        title="Analyse"
        description="Velg prosjekt for å følge gjennomgangen, lese funn og åpne kildene."
      />
      <section className="dashboard-card dashboard-card--padded analysis-hero">
        <div className="analysis-hero__header">
          <div>
            <div className="section-kicker">Prosjektgjennomgang</div>
            <h2>Varige jobber, funn og kildegrunnlag</h2>
          </div>
          <button
            className="button button--secondary"
            type="button"
            onClick={refresh}
          >
            Oppdater prosjektlisten
          </button>
        </div>
        <p>
          Åpne et prosjekt for å starte eller gjenoppta en gjennomgang. Lagrede
          resultater, manuell kontroll og rapporter følger jobbens snapshot.
        </p>
        <p className="memory-muted">
          Å åpne eller oppdatere denne siden starter ingen analyse. Nye
          vurderinger kan bruke OpenAI og startes bare fra prosjektets
          gjennomgang.
        </p>
      </section>
      {projectsError ? (
        <ErrorState
          title="Prosjektene kunne ikke hentes"
          description={projectsError}
          action={
            <button
              type="button"
              className="button button--secondary"
              onClick={refresh}
            >
              Prøv igjen
            </button>
          }
        />
      ) : projectsLoading ? (
        <p role="status">Laster prosjekter …</p>
      ) : (
        <section className="dashboard-card dashboard-card--padded analysis-projects">
          <div className="section-head">
            <h2 className="section-title">Velg prosjekt</h2>
            <span>{projects.length} prosjekter</span>
          </div>
          <ProjectTable
            projects={projects}
            onAnalyzeProject={(project) =>
              navigate(projectUrl(project.projectName, "review"))
            }
          />
        </section>
      )}
    </div>
  );
}
