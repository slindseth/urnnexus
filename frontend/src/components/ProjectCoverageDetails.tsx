import type { SyncCoverage } from "../types";
import { formatActivityTimestamp } from "../lib/activity";

const syncLabels = {
  complete: "Fullført",
  incomplete: "Ufullstendig",
  failed: "Feilet",
  unknown: "Ukjent",
};

export function ProjectCoverageDetails({
  coverage,
}: {
  coverage?: SyncCoverage;
}) {
  const exclusions =
    coverage?.historical_analysis_exclusions ??
    coverage?.analysis_exclusions ??
    [];
  const groups = new Map<
    string,
    Array<{
      message: string;
      observed_at?: string | null;
      run_id?: string | null;
    }>
  >();
  for (const item of coverage?.historical_coverage_diagnostics ?? [])
    groups.set(item.message, [...(groups.get(item.message) ?? []), item]);
  return (
    <section
      className="surface surface--padded"
      aria-label="Synkronisering og analysedekning"
    >
      <h2 className="section-title">Synkronisering og analysedekning</h2>
      <p>
        Sync-fullføring:{" "}
        <strong>{syncLabels[coverage?.sync_status ?? "unknown"]}</strong> ·
        Enumerering:{" "}
        {coverage?.enumeration_complete === true
          ? "Fullført"
          : coverage?.enumeration_complete === false
            ? "Ufullstendig"
            : "Ukjent"}
      </p>
      <p>
        Siste komplette kildegrunnlag:{" "}
        {formatActivityTimestamp(coverage?.source_snapshot_at)} · Snapshot:{" "}
        {coverage?.source_snapshot_status ?? "Ukjent"}
      </p>
      <p>
        Analysestatus: {coverage?.analysis_status ?? "Ukjent"}. Synkronisering
        og analysedekning vurderes separat. Rapporter kan ha begrenset dekning.
      </p>
      {exclusions.length ? (
        <details open>
          <summary>
            Registrerte begrensninger i kildedekning ({exclusions.length})
          </summary>
          <p>
            Historiske begrensninger beholdes som dokumentasjon; tidspunktet
            gjelder observasjonen.
          </p>
          <ul>
            {exclusions.map((item, index) => (
              <li key={index}>
                <strong>
                  {String(
                    item.relative_path ??
                      item.path ??
                      item.document ??
                      "Ukjent fil",
                  )}
                </strong>{" "}
                ·{" "}
                {String(
                  item.reason ?? item.exclusion_reason ?? "Ikke analysert",
                )}
                {item.observed_at
                  ? ` · ${formatActivityTimestamp(String(item.observed_at))}`
                  : null}
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <p>
          Ingen policyutelatelser er dokumentert i den tilgjengelige
          synkhistorikken. Parserbegrensninger vises i prosjektgjennomgangen.
        </p>
      )}
      {coverage?.historical_coverage_diagnostics?.length ? (
        <details>
          <summary>
            Historiske parser- og filbegrensninger (
            {coverage.historical_coverage_diagnostics.length})
          </summary>
          <ul>
            {[...groups].map(([message, occurrences]) => (
              <li key={message}>
                <details>
                  <summary>
                    {message} · {occurrences.length} forekomster · Først:{" "}
                    {formatActivityTimestamp(occurrences.at(-1)?.observed_at)} ·
                    Sist: {formatActivityTimestamp(occurrences[0]?.observed_at)}
                  </summary>
                  <ol>
                    {occurrences.map((item, index) => (
                      <li key={index}>
                        {formatActivityTimestamp(item.observed_at)} · Kjøring:{" "}
                        {item.run_id ?? "Ukjent"}
                      </li>
                    ))}
                  </ol>
                </details>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
