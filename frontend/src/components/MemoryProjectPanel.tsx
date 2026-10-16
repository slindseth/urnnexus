import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  formatDateTime,
  getUserFacingErrorMessage,
  projectUrl,
} from "../lib/api";
import { useMemoryJob } from "../lib/useMemoryJob";
import {
  cancelMemory,
  jobLabels,
  locationLabel,
  memoryEvidence,
  memoryEvents,
  memoryFindings,
  memoryManual,
  memoryReferences,
  memoryReports,
  memoryViews,
  stageLabels,
  type ManualUnit,
  type MemoryEvidence,
  type MemoryFinding,
  type MemoryJob,
  type MemoryReference,
  type MemoryReport,
  type MemoryView,
} from "../lib/memory";
import { StatusPill } from "./StatusPill";

const categoryNames: Record<string, string> = {
  contradiction: "Motstrid",
  risk: "Risiko",
  question: "Åpent spørsmål",
  dependency: "Avhengighet",
};

export function MemoryProjectPanel({
  projectName,
  variant = "review",
}: {
  projectName: string;
  variant?: "review" | "summary" | "reports";
}) {
  const data = useMemoryJob(projectName);
  const { status, listing, loading, error, starting, actionError } = data;
  const job = status?.job;
  const [confirmFull, setConfirmFull] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [controlError, setControlError] = useState<string | null>(null);
  async function stop() {
    if (!job) return;
    setStopping(true);
    setControlError(null);
    try {
      await cancelMemory(projectName, job.job_id);
      data.reload();
    } catch (reason) {
      setControlError(
        getUserFacingErrorMessage(
          reason,
          "Stoppforespørselen kunne ikke sendes.",
        ),
      );
    } finally {
      setStopping(false);
    }
  }
  const busy = Boolean(
    starting || status?.worker_active || listing?.worker_active,
  );
  const tone =
    job?.status === "failed"
      ? "danger"
      : job?.status === "completed"
        ? "success"
        : job?.status === "running"
          ? "info"
          : "warning";

  return (
    <section
      className="surface surface--padded memory-panel"
      aria-label="Prosjektgjennomgang"
    >
      <div className="section-head">
        <div>
          <div className="section-kicker">Prosjektminne</div>
          <h2 className="section-title">
            {variant === "reports"
              ? "Rapporter fra prosjektmotoren"
              : "Gjennomgang og kildegrunnlag"}
          </h2>
        </div>
        <button
          className="button button--secondary"
          onClick={data.reload}
          type="button"
        >
          Oppdater gjennomgang
        </button>
      </div>
      {error ? (
        <div className="inline-note memory-error" role="alert">
          <strong>Gjennomgangen er utilgjengelig.</strong> {error}{" "}
          <button
            type="button"
            className="button button--secondary"
            onClick={data.reload}
          >
            Prøv igjen
          </button>
        </div>
      ) : null}
      {loading && !job ? (
        <p role="status">Laster lagret prosjektgjennomgang …</p>
      ) : null}
      {listing && !error ? (
        <>
          {listing.jobs.length ? (
            <div className="memory-job-picker">
              <label htmlFor={`memory-job-${variant}`}>Jobb og snapshot</label>
              <select
                id={`memory-job-${variant}`}
                value={job?.job_id ?? listing.jobs[0].id}
                onChange={(event) => data.select(event.target.value)}
              >
                {job && !listing.jobs.some((row) => row.id === job.job_id) ? (
                  <option value={job.job_id}>{job.job_id}</option>
                ) : null}
                {listing.jobs.map((row) => (
                  <option key={row.id} value={row.id}>
                    {formatDateTime(row.created_at)} ·{" "}
                    {jobLabels[row.status] ?? row.status} · {row.id}
                  </option>
                ))}
              </select>
              {listing.next_after !== null ? (
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => void data.older()}
                >
                  Vis eldre jobber
                </button>
              ) : null}
            </div>
          ) : !loading ? (
            <p>
              Ingen gjennomgang er lagret. Velg «Start gjennomgang» for å sende
              prosjektets lesbare innhold til OpenAI via appliance.
            </p>
          ) : null}
          {job ? (
            <>
              <div className="memory-state">
                <StatusPill
                  status={job.status}
                  label={jobLabels[job.status] ?? job.status}
                  tone={tone}
                />
                <span>{stageLabels[job.stage] ?? job.stage}</span>
              </div>
              <div className="memory-identifiers">
                <span>
                  Jobb <code>{job.job_id}</code>
                </span>
                <span>
                  Snapshot <code>{job.snapshot_id}</code>
                </span>
                <span>Analysert {formatDateTime(job.created_at)}</span>
              </div>
              {status?.historical ? (
                <div className="inline-note memory-warning">
                  Historisk snapshot. En nyere prosjektversjon finnes i en annen
                  jobb.
                </div>
              ) : null}
              {job.stale ||
              job.status === "stale" ||
              status?.freshness.state === "changed" ? (
                <div className="inline-note memory-warning" role="status">
                  Kildegrunnlaget er endret. Funn og rapport gjelder snapshotet
                  over. Start en ny inkrementell gjennomgang for oppdatert
                  resultat.
                  {status?.freshness.changed.length ? (
                    <p>Endret: {status.freshness.changed.join(", ")}</p>
                  ) : null}
                </div>
              ) : null}
              {status?.freshness.state === "unknown" ? (
                <p className="memory-muted">
                  Noen kilder er ikke kontrollert eller finnes ikke i lokal
                  cache. Aktualitet er ikke bekreftet.
                </p>
              ) : null}
              <p className="memory-muted">{status?.freshness.scope}</p>
              {job.status === "partial" || job.manual_review_units > 0 ? (
                <div className="inline-note memory-warning">
                  <strong>Delvis gjennomgått.</strong> Rapporten kan brukes med
                  de oppgitte begrensningene. {job.manual_review_units}{" "}
                  enhet(er) krever manuell kontroll.
                </div>
              ) : null}
              {job.provider === "fixture" ? (
                <div className="inline-note memory-warning">
                  Testkjøring uten modellvurdering. Dette er ikke en faglig
                  analyse.
                </div>
              ) : null}
              {job.status === "running" && !status?.worker_active ? (
                <div className="inline-note memory-warning">
                  Jobben er registrert som pågående, men ingen arbeider kjører.
                  Gjenoppta den eksisterende jobben.
                </div>
              ) : null}
              {job.status === "failed" ? (
                <div className="inline-note memory-error" role="alert">
                  Gjennomgangen stoppet med feil. Fullførte arbeidsenheter er
                  lagret og kan gjenbrukes ved gjenopptak.
                </div>
              ) : null}
              <Coverage job={job} />
              <p className="memory-muted">
                Behandlingsdekning er ikke et mål på nøyaktighet. Ferdige
                seksjoner eller ingen funn garanterer ikke et komplett eller
                feilfritt grunnlag.
              </p>
            </>
          ) : null}
          {variant !== "reports" && listing.actions_enabled ? (
            <div className="memory-actions">
              <button
                className="button"
                disabled={busy}
                type="button"
                onClick={() => void data.run("incremental")}
              >
                {starting
                  ? "Starter arbeider …"
                  : job
                    ? "Oppdater analyse"
                    : "Start gjennomgang"}
              </button>
              {status?.can_resume ? (
                <button
                  className="button button--secondary"
                  disabled={busy}
                  type="button"
                  onClick={() => void data.run("resume")}
                >
                  Gjenoppta samme jobb
                </button>
              ) : null}
              {status?.worker_active && job?.status === "running" ? (
                <button
                  className="button button--secondary"
                  disabled={stopping || status.cancellation_requested}
                  type="button"
                  onClick={() => void stop()}
                >
                  {status.cancellation_requested
                    ? "Stopp er forespurt"
                    : "Be om stopp"}
                </button>
              ) : null}
              {job ? (
                <button
                  className="button button--secondary"
                  disabled={busy}
                  type="button"
                  onClick={() => setConfirmFull(true)}
                >
                  Full reanalyse …
                </button>
              ) : null}
            </div>
          ) : null}
          {!listing.actions_enabled ? (
            <p className="memory-muted">
              Jobbkontroll er slått av på denne Nexus-serveren. Lagrede
              resultater kan fortsatt leses.
            </p>
          ) : variant !== "reports" ? (
            <p className="memory-muted">
              Analyse starter bare ved et aktivt valg. Nye vurderinger kan bruke
              OpenAI. Denne arbeidsflyten sender ikke e-post eller laster opp
              rapporter.
            </p>
          ) : null}
          {status?.cancellation_requested ? (
            <p role="status">
              Stoppforespørselen er lagret. Et aktivt API-kall kan fullføres før
              arbeideren stopper.
            </p>
          ) : null}
          {actionError || controlError ? (
            <div className="inline-note memory-error" role="alert">
              {actionError ?? controlError}
            </div>
          ) : null}
          {variant === "summary" ? (
            <Link
              className="button button--secondary"
              to={
                projectUrl(projectName, "review") +
                (job ? `?job=${encodeURIComponent(job.job_id)}` : "")
              }
            >
              Åpne funn og kilder
            </Link>
          ) : null}
          {job ? (
            <MemoryReports
              key={`${projectName}:${job.job_id}:${data.revision}`}
              project={projectName}
              job={job}
            />
          ) : null}
          {job && variant === "review" ? (
            <>
              <MemoryViews
                key={`${job.job_id}:${job.status === "running" ? "running" : job.updated_at}:${data.revision}`}
                project={projectName}
                job={job}
              />
              <MemoryFindings
                key={`${projectName}:${job.job_id}:${job.status === "running" ? "running" : job.updated_at}:${data.revision}`}
                project={projectName}
                job={job}
              />
              <MemoryGaps
                key={`${projectName}:${job.job_id}:${data.revision}`}
                project={projectName}
                job={job}
              />
              <MemoryProgress
                key={`${projectName}:${job.job_id}`}
                project={projectName}
                job={job}
              />
            </>
          ) : null}
          {confirmFull ? (
            <FullDialog
              onCancel={() => setConfirmFull(false)}
              onConfirm={() => {
                setConfirmFull(false);
                void data.run("full");
              }}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function FullDialog({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal-panel memory-dialog"
      aria-labelledby="memory-full-title"
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
    >
      <h2 id="memory-full-title">Full reanalyse av prosjektet?</h2>
      <p>
        Dette bestiller nye vurderinger av alle lesbare seksjoner, også når
        kildene er uendret. Det kan gi nye API-kostnader. Tidligere rapporter
        beholdes.
      </p>
      <div className="memory-actions">
        <button
          type="button"
          className="button button--secondary"
          autoFocus
          onClick={onCancel}
        >
          Avbryt
        </button>
        <button type="button" className="button" onClick={onConfirm}>
          Start full reanalyse
        </button>
      </div>
    </dialog>
  );
}

function Coverage({ job }: { job: MemoryJob }) {
  const counts = [
    ["Kildefiler", `${job.files_supported} / ${job.files_discovered}`],
    ["Native enheter", job.native_units],
    ["Seksjoner vurdert", job.batches_reviewed],
    ["Ventende seksjoner", job.batches_pending],
    ["Feilede seksjoner", job.batches_failed],
    ["Manuell kontroll", job.manual_review_units],
  ];
  return (
    <>
      <dl className="memory-counts">
        {counts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {job.processing_errors?.length ? (
        <ul className="memory-error">
          {job.processing_errors.map((error) => (
            <li key={error.id}>
              {error.operation}: {error.error}
            </li>
          ))}
        </ul>
      ) : null}
      <details>
        <summary>Arbeid og API-forbruk</summary>
        <ul>
          {job.batches.map((batch) => (
            <li key={`${batch.operation}:${batch.status}`}>
              {batch.operation} · {batch.status}: {batch.count}
            </li>
          ))}
        </ul>
        <p>
          {job.usage.calls} registrerte API-kall ·{" "}
          {job.usage.input_tokens.toLocaleString("nb-NO")} inputtokens ·{" "}
          {job.usage.output_tokens.toLocaleString("nb-NO")} outputtokens.{" "}
          {job.usage.cost === null
            ? "Pengekostnad er ikke beregnet."
            : `Konfigurert kostnadsberegning: ${job.usage.cost}`}
        </p>
        <p>
          Forbruket gjelder hele jobben, også tidligere forsøk. Å oppdatere
          visningen bruker ingen nye analysekall.
        </p>
      </details>
    </>
  );
}

function MemoryReports({ project, job }: { project: string; job: MemoryJob }) {
  const [rows, setRows] = useState<MemoryReport[]>([]),
    [next, setNext] = useState<number | null>(null),
    [error, setError] = useState<string | null>(null),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    memoryReports(project, job.job_id)
      .then((value) => {
        if (active) {
          setRows(value.reports);
          setNext(value.next_after);
        }
      })
      .catch((e) => {
        if (active)
          setError(
            getUserFacingErrorMessage(e, "Rapportene kunne ikke hentes."),
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [project, job.job_id, job.status, job.report_id]);
  async function more() {
    if (next === null) return;
    try {
      const value = await memoryReports(project, job.job_id, next);
      setRows((old) => [...old, ...value.reports]);
      setNext(value.next_after);
    } catch (e) {
      setError(
        getUserFacingErrorMessage(e, "Eldre rapporter kunne ikke hentes."),
      );
    }
  }
  return (
    <section className="memory-section">
      <h3>Word-rapporter fra valgt jobb</h3>
      {error ? (
        <p role="alert" className="memory-error">
          {error}
        </p>
      ) : loading ? (
        <p>Laster rapportreferanser …</p>
      ) : !rows.length ? (
        <p>Ingen lagret rapport er tilgjengelig for denne jobben ennå.</p>
      ) : (
        <ul className="memory-report-list">
          {rows.map((report) => (
            <li key={report.report_id}>
              <div>
                <strong>{report.name}</strong>
                {report.report_id === job.report_id ? (
                  <span className="memory-muted">
                    {" "}
                    · Gjeldende rapport for jobben
                  </span>
                ) : (
                  <span className="memory-muted">
                    {" "}
                    · Tidligere rapportutgave
                  </span>
                )}
                <p>{formatDateTime(report.created_at)}</p>
                <code>{report.report_id}</code>
              </div>
              <div className="memory-actions">
                <a
                  className="button button--secondary"
                  href={report.preview_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Forhåndsvis tekst
                </a>
                <a className="button" href={report.download_url}>
                  Last ned Word
                </a>
              </div>
            </li>
          ))}
        </ul>
      )}
      {next !== null ? (
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void more()}
        >
          Vis flere rapportutgaver
        </button>
      ) : null}
    </section>
  );
}

function MemoryFindings({ project, job }: { project: string; job: MemoryJob }) {
  const [rows, setRows] = useState<MemoryFinding[]>([]),
    [next, setNext] = useState<number | null>(null),
    [error, setError] = useState<string | null>(null),
    [loading, setLoading] = useState(false),
    [filter, setFilter] = useState("all");
  const finished = job.status !== "running";
  useEffect(() => {
    if (!finished) return;
    let active = true;
    setLoading(true);
    memoryFindings(project, job.job_id)
      .then((r) => {
        if (active) {
          setRows(r.findings);
          setNext(r.next_after);
        }
      })
      .catch((e) => {
        if (active)
          setError(getUserFacingErrorMessage(e, "Funnene kunne ikke hentes."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [project, job.job_id, finished]);
  async function more() {
    if (next === null) return;
    setLoading(true);
    try {
      const r = await memoryFindings(project, job.job_id, next);
      setRows((old) => [...old, ...r.findings]);
      setNext(r.next_after);
    } catch (e) {
      setError(getUserFacingErrorMessage(e, "Flere funn kunne ikke hentes."));
    } finally {
      setLoading(false);
    }
  }
  const supported = rows.filter((r) => r.verification.supported === true),
    rejected = rows.filter((r) => r.verification.supported !== true);
  const visible =
    filter === "all"
      ? supported
      : supported.filter(
          (r) => r.category === filter || r.categories?.includes(filter),
        );
  return (
    <section className="memory-section">
      <div className="section-head">
        <h3>Kontrollerte funn og åpne spørsmål</h3>
        <label>
          Vis kategori{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">Alle viste funn</option>
            {Object.entries(categoryNames).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p>
        Funnene er kildekontrollert av analysemotoren og kan trenge menneskelig
        fagkontroll.
      </p>
      {job.consolidation ? (
        <p>
          {job.consolidation.raw_verified} kildeverifiserte forslag er samlet
          til {job.consolidation.reported_verified} forhold. Åpne et funn for
          originalforslag og alle kildene.
        </p>
      ) : null}
      {!finished ? (
        <p>
          Gjennomgangen pågår. Den ferdige funnlisten publiseres etter
          verifisering og konsolidering.
        </p>
      ) : loading && !rows.length ? (
        <p>Laster funn …</p>
      ) : null}
      {error ? (
        <p className="memory-error" role="alert">
          {error}
        </p>
      ) : null}
      {finished && !loading && !error && !supported.length ? (
        <p>
          Ingen kildeverifiserte funn i den innlastede delen. Dette bekrefter
          ikke at prosjektet er uten risiko.
        </p>
      ) : null}
      {visible.map((finding) => (
        <FindingCard
          key={finding.id}
          project={project}
          job={job.job_id}
          finding={finding}
        />
      ))}
      {rejected.length ? (
        <details>
          <summary>{rejected.length} modellforslag ble ikke bekreftet</summary>
          <p>Disse forslagene inngår ikke i listen over kontrollerte funn.</p>
          {rejected.map((finding) => (
            <FindingCard
              key={finding.id}
              project={project}
              job={job.job_id}
              finding={finding}
            />
          ))}
        </details>
      ) : null}
      {next !== null ? (
        <button
          type="button"
          className="button button--secondary"
          disabled={loading}
          onClick={() => void more()}
        >
          Last flere funn
        </button>
      ) : null}
    </section>
  );
}

function FindingCard({
  project,
  job,
  finding,
}: {
  project: string;
  job: string;
  finding: MemoryFinding;
}) {
  const [open, setOpen] = useState(false);
  const uncertainties = [
    ...new Set(
      [finding.uncertainty, finding.verification.uncertainty].filter(Boolean),
    ),
  ];
  return (
    <details
      className="memory-finding"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span className="memory-finding-title">{finding.title}</span>
        <span className="memory-muted">
          {categoryNames[finding.category] ?? finding.category} ·{" "}
          {finding.evidence.length} kilder
          {finding.member_ids
            ? ` · ${finding.member_ids.length} samlede forslag`
            : ""}
        </span>
      </summary>
      <p className="memory-prewrap">{finding.conclusion}</p>
      <h4>Usikkerhet og avgrensning</h4>
      {uncertainties.length ? (
        uncertainties.map((u) => (
          <p className="memory-prewrap" key={u}>
            {u}
          </p>
        ))
      ) : (
        <p>Ingen særskilt usikkerhet er oppgitt.</p>
      )}
      <h4>Anbefalt avklaring</h4>
      <p className="memory-prewrap">{finding.recommended_check}</p>
      {!finding.verification.supported ? (
        <p className="memory-error">
          Ikke kildebekreftet: {finding.verification.reason}
        </p>
      ) : null}
      {finding.member_findings ? (
        <details>
          <summary>Originalforslag og samlingsgrunnlag</summary>
          <p>{finding.consolidation?.reason}</p>
          <p>{finding.consolidation?.scope}</p>
          {finding.member_findings.map((m) => (
            <article className="memory-member" key={m.id}>
              <strong>{m.title}</strong>
              <p>{m.conclusion}</p>
              <p>{m.uncertainty}</p>
              <p>{m.recommended_check}</p>
              <code>{m.id}</code>
            </article>
          ))}
        </details>
      ) : null}
      <h4>Kilder fra dette snapshotet</h4>
      {open ? (
        <EvidenceList project={project} job={job} ids={finding.evidence} />
      ) : null}
      <p className="memory-muted">
        <code>{finding.id}</code>
      </p>
    </details>
  );
}

function EvidenceList({
  project,
  job,
  ids,
}: {
  project: string;
  job: string;
  ids: string[];
}) {
  const [count, setCount] = useState(6);
  return (
    <>
      <div className="memory-evidence-list">
        {ids.slice(0, count).map((id) => (
          <EvidenceCard key={id} project={project} job={job} id={id} />
        ))}
      </div>
      {count < ids.length ? (
        <button
          type="button"
          className="button button--secondary"
          onClick={() => setCount((old) => old + 6)}
        >
          Vis flere kilder ({ids.length - count} gjenstår)
        </button>
      ) : null}
    </>
  );
}

function EvidenceCard({
  project,
  job,
  id,
}: {
  project: string;
  job: string;
  id: string;
}) {
  const [value, setValue] = useState<MemoryEvidence | null>(null),
    [error, setError] = useState<string | null>(null),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError(null);
    memoryEvidence(project, job, id)
      .then((r) => {
        if (active) setValue(r);
      })
      .catch((e) => {
        if (active)
          setError(getUserFacingErrorMessage(e, "Kilden kunne ikke hentes."));
      });
    return () => {
      active = false;
    };
  }, [project, job, id, retry]);
  return (
    <article className="memory-evidence">
      {error ? (
        <>
          <p role="alert" className="memory-error">
            {error}
          </p>
          <button
            type="button"
            className="button button--secondary"
            onClick={() => setRetry((old) => old + 1)}
          >
            Prøv kilden igjen
          </button>
        </>
      ) : value ? (
        <>
          <h5>{value.path}</h5>
          <p>{locationLabel(value.locator)}</p>
          <blockquote>{value.excerpt}</blockquote>
          <p>Registrert utsagn: {value.statement}</p>
          {value.uncertainty ? <p>Forbehold: {value.uncertainty}</p> : null}
          <a
            href={value.source_url}
            className="button button--secondary"
            target="_blank"
            rel="noreferrer"
          >
            Åpne lagret kildeversjon
          </a>
          <details>
            <summary>Kildeidentitet</summary>
            <p>
              Dokumentversjon <code>{value.document_version_id}</code>
            </p>
            <p>
              Kildelokasjon <code>{value.source_location_id}</code>
            </p>
            <p>
              Evidens <code>{value.evidence_id}</code>
            </p>
            <p>
              SHA256 <code>{value.source_hash}</code>
            </p>
          </details>
        </>
      ) : (
        <p>Laster kilde …</p>
      )}
    </article>
  );
}

function MemoryViews({ project, job }: { project: string; job: MemoryJob }) {
  const [open, setOpen] = useState(false);
  const [overview, setOverview] = useState<MemoryView | null>(null);
  const [topics, setTopics] = useState<MemoryView[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (!open || job.status === "running") return;
    let active = true;
    memoryViews(project, job.job_id)
      .then((r) => {
        if (active) {
          setOverview(r.overview);
          setTopics(r.topics);
          setNext(r.next_after);
          setLoaded(true);
        }
      })
      .catch((e) => {
        if (active)
          setError(
            getUserFacingErrorMessage(e, "Oversiktene kunne ikke hentes."),
          );
      });
    return () => {
      active = false;
    };
  }, [open, project, job.job_id, job.status]);
  async function more() {
    if (next === null) return;
    try {
      const r = await memoryViews(project, job.job_id, next);
      setTopics((old) => [...old, ...r.topics]);
      setNext(r.next_after);
    } catch (e) {
      setError(getUserFacingErrorMessage(e, "Temaene kunne ikke hentes."));
    }
  }
  return (
    <details
      className="memory-section"
      onToggle={(e) => {
        if (e.target === e.currentTarget) setOpen(e.currentTarget.open);
      }}
    >
      <summary>Prosjektoversikt og temaoppsummeringer</summary>
      {error ? (
        <p role="alert" className="memory-error">
          {error}
        </p>
      ) : null}
      {overview ? (
        <MemorySummary project={project} job={job} view={overview} overview />
      ) : loaded ? (
        <p>Ingen prosjektoversikt er tilgjengelig for valgt jobb.</p>
      ) : (
        <p>
          {job.status === "running"
            ? "Oversikter vises når gjennomgangen er avsluttet."
            : "Laster oversikter …"}
        </p>
      )}
      {topics.map((topic) => (
        <MemorySummary
          key={topic.id}
          project={project}
          job={job}
          view={topic}
        />
      ))}
      {next !== null ? (
        <button
          className="button button--secondary"
          type="button"
          onClick={() => void more()}
        >
          Vis flere temaer
        </button>
      ) : null}
    </details>
  );
}

function MemorySummary({
  project,
  job,
  view,
  overview = false,
}: {
  project: string;
  job: MemoryJob;
  view: MemoryView;
  overview?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      onToggle={(e) => {
        if (e.target === e.currentTarget) setOpen(e.currentTarget.open);
      }}
    >
      <summary>{overview ? "Prosjektoversikt" : `Tema: ${view.label}`}</summary>
      <p>
        {overview
          ? view.verified
            ? "Kildeverifisert maskinoversikt"
            : "Foreløpig – ikke kildeverifisert"
          : "Maskinbasert temaoppsummering"}{" "}
        · Snapshot <code>{view.snapshot ?? job.snapshot_id}</code>
      </p>
      <p className="memory-prewrap">{view.overview}</p>
      {view.limitations.map((l, index) => (
        <p key={index}>Begrensning: {l}</p>
      ))}
      {open ? (
        <EvidenceList project={project} job={job.job_id} ids={view.evidence} />
      ) : null}
    </details>
  );
}

function MemoryGaps({ project, job }: { project: string; job: MemoryJob }) {
  const [open, setOpen] = useState(false),
    [units, setUnits] = useState<ManualUnit[]>([]),
    [references, setReferences] = useState<MemoryReference[]>([]),
    [unitNext, setUnitNext] = useState<number | null>(null),
    [refNext, setRefNext] = useState<number | null>(null),
    [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    let active = true;
    Promise.all([
      memoryManual(project, job.job_id),
      memoryReferences(project, job.job_id),
    ])
      .then(([u, r]) => {
        if (active) {
          setUnits(u.units);
          setUnitNext(u.next_after);
          setReferences(r.references);
          setRefNext(r.next_after);
        }
      })
      .catch((e) => {
        if (active)
          setError(
            getUserFacingErrorMessage(e, "Kontrollpunktene kunne ikke hentes."),
          );
      });
    return () => {
      active = false;
    };
  }, [open, project, job.job_id, job.status]);
  async function more(kind: "units" | "references") {
    try {
      if (kind === "units" && unitNext !== null) {
        const r = await memoryManual(project, job.job_id, unitNext);
        setUnits((old) => [...old, ...r.units]);
        setUnitNext(r.next_after);
      }
      if (kind === "references" && refNext !== null) {
        const r = await memoryReferences(project, job.job_id, refNext);
        setReferences((old) => [...old, ...r.references]);
        setRefNext(r.next_after);
      }
    } catch (e) {
      setError(
        getUserFacingErrorMessage(
          e,
          "Flere kontrollpunkter kunne ikke hentes.",
        ),
      );
    }
  }
  return (
    <details
      className="memory-section"
      onToggle={(e) => {
        if (e.target === e.currentTarget) setOpen(e.currentTarget.open);
      }}
    >
      <summary>Manuell kontroll og referanser</summary>
      <p>
        Kontrollstatus må følges opp utenfor Nexus. Å åpne en kilde endrer ikke
        tilstanden.
      </p>
      {error ? (
        <p role="alert" className="memory-error">
          {error}
        </p>
      ) : null}
      <h4>Enheter som krever kontroll</h4>
      {!units.length ? (
        <p>Ingen manuelle enheter i den innlastede delen.</p>
      ) : (
        units.map((u) => (
          <article key={u.id} className="memory-member">
            <strong>{u.path}</strong>
            <p>
              {locationLabel(u.locator)} · {u.state}
            </p>
            <p className="memory-prewrap">
              {typeof u.quality === "string"
                ? u.quality
                : JSON.stringify(u.quality)}
            </p>
            <code>{u.version}</code>
            {u.source_url ? (
              <p>
                <a href={u.source_url} target="_blank" rel="noreferrer">
                  Åpne denne kildeversjonen
                </a>
              </p>
            ) : null}
          </article>
        ))
      )}
      {unitNext !== null ? (
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void more("units")}
        >
          Flere manuelle enheter
        </button>
      ) : null}
      <h4>Deklarerte og uløste referanser</h4>
      {references.length ? (
        <ul>
          {references.map((r, index) => (
            <li key={`${r.work_id}:${index}`}>
              {r.reference} · {r.state}
            </li>
          ))}
        </ul>
      ) : (
        <p>Ingen referanser i den innlastede delen.</p>
      )}
      {refNext !== null ? (
        <button
          type="button"
          className="button button--secondary"
          onClick={() => void more("references")}
        >
          Flere referanser
        </button>
      ) : null}
    </details>
  );
}

function MemoryProgress({ project, job }: { project: string; job: MemoryJob }) {
  const [open, setOpen] = useState(false),
    [events, setEvents] = useState<
      Array<{
        sequence: number;
        stage: string;
        status: string;
        created_at: string;
      }>
    >([]),
    [next, setNext] = useState(0),
    [error, setError] = useState<string | null>(null);
  async function load(after = 0) {
    try {
      const r = await memoryEvents(project, job.job_id, after);
      setEvents((old) => (after ? [...old, ...r.events] : r.events));
      setNext(r.next_after);
    } catch (e) {
      setError(getUserFacingErrorMessage(e, "Progresjonen kunne ikke hentes."));
    }
  }
  return (
    <details
      className="memory-section"
      onToggle={(e) => {
        if (e.target === e.currentTarget) {
          setOpen(e.currentTarget.open);
          if (e.currentTarget.open && !events.length) void load();
        }
      }}
    >
      <summary>Varig progresjonslogg</summary>
      {open ? (
        <>
          {error ? <p role="alert">{error}</p> : null}
          <ol className="memory-events">
            {events.map((e) => (
              <li key={e.sequence}>
                <time>{formatDateTime(e.created_at)}</time>{" "}
                {stageLabels[e.stage] ?? e.stage} ·{" "}
                {jobLabels[e.status] ?? e.status}
              </li>
            ))}
          </ol>
          <button
            className="button button--secondary"
            type="button"
            onClick={() => void load(next)}
          >
            Hent neste hendelser
          </button>
        </>
      ) : null}
    </details>
  );
}
