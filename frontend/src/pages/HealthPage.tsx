import { useId, type ReactNode } from "react";
import { AppHeader } from "../components/Layout";
import { EmptyState } from "../components/EmptyState";
import { StatusPill } from "../components/StatusPill";
import { formatBytes, formatDateTime } from "../lib/api";
import { useAppData } from "../context/AppDataContext";

export function HealthPage() {
  const { health, healthLoading, healthError, projects } = useAppData();

  if (healthError) {
    return <EmptyState title="Kunne ikke hente helse" description={healthError} />;
  }

  return (
    <div className="page-stack">
      <AppHeader title="Helse" description="Tilgjengelighet, synkronisering og kapasitet i ett overblikk." />

      {healthLoading ? (
        <section className="surface surface--padded">
          <div className="loading-copy">Laster helsestatus …</div>
        </section>
      ) : !health ? (
        <EmptyState title="Kunne ikke hente helse" description="API-et returnerte ikke helsedata." />
      ) : (
        <section className="surface surface--padded health-surface">
          <div className="health-surface__head">
            <h2>Systemstatus</h2>
            <span>Siste tilgjengelige driftssignal</span>
          </div>
          <div className="health-grid">
            <HealthInfoCard label="Tilgjengelig" tooltip="Viser om Nexus-backend svarer på API-kall.">
              <StatusPill status={health.appliance_available ? "online" : "offline"} label={health.appliance_available ? "Ja" : "Nei"} />
            </HealthInfoCard>
            <HealthInfoCard label="Oppetid" tooltip="Hvor lenge Nexus-backend har kjørt siden siste restart.">
              {health.uptime}
            </HealthInfoCard>
            <HealthInfoCard label="Versjon" tooltip="Gjeldende Nexus-versjon. Tallet øker automatisk med hver commit.">
              {health.version ?? "—"}
            </HealthInfoCard>
            <HealthInfoCard label="Prosjekter i visning" tooltip="Antall prosjekter som faktisk er synlige i denne visningen akkurat nå.">
              {projects.length.toLocaleString("nb-NO")}
            </HealthInfoCard>

            <HealthInfoCard
              label="Prosjekter totalt"
              tooltip="Totalt antall prosjekter backend har funnet i datagrunnlaget. Noen prosjekter kan være skjult i UI-et, for eksempel sample-prosjekter."
            >
              {health.project_count.toLocaleString("nb-NO")}
            </HealthInfoCard>
            <HealthInfoCard label="Antall filer" tooltip="Totalt antall kildefiler funnet i viste prosjekter.">
              {health.file_count.toLocaleString("nb-NO")}
            </HealthInfoCard>
            <HealthInfoCard label="Rapporter" tooltip="Antall kommentardokumenter/rapporter funnet i viste prosjekter.">
              {health.report_count.toLocaleString("nb-NO")}
            </HealthInfoCard>
            <HealthInfoCard label="Siste synk" tooltip="Siste fullførte OneDrive-sync registrert av Nexus.">
              {health.last_synced_at ? formatDateTime(health.last_synced_at) : "—"}
            </HealthInfoCard>

            <HealthInfoCard label="Siste analyse" tooltip="Siste analyse registrert fra Appliance-state. Skal ikke endres ved sync-only.">
              {health.last_analyzed_at ? formatDateTime(health.last_analyzed_at) : "—"}
            </HealthInfoCard>
            <HealthInfoCard label="Siste rapport opprettet" tooltip="Siste opprettede kommentardokument, basert på created time der det finnes.">
              {health.latest_report_generated_at ? formatDateTime(health.latest_report_generated_at) : "—"}
            </HealthInfoCard>
            <HealthInfoCard label="OneDrive-status" tooltip="Lokal OneDrive-cache. Dette bekrefter ikke Microsoft-innlogging eller nettverkstilgang.">
              <StatusPill status={health.one_drive_status} />
            </HealthInfoCard>
            <HealthInfoCard label="Graph-write" tooltip="Viser registrert konfigurasjon. Innlogging, tillatelser og ekstern opplasting er ikke dermed verifisert.">
              <StatusPill status={health.graph_write_status} />
            </HealthInfoCard>
            <HealthInfoCard label="Microsoft-innlogging" tooltip="Krever faktisk observert autentisering. Lokal cache og konfigurasjon er ikke tilstrekkelig.">
              {health.microsoft_auth_verified === true ? "Verifisert" : "Ikke verifisert"}
            </HealthInfoCard>
            <HealthInfoCard label="Ekstern rapportopplasting" tooltip="Krever faktisk bekreftet opplasting, ikke bare en generert rapport.">
              {health.external_upload_verified === true ? "Verifisert" : "Ikke verifisert"}
            </HealthInfoCard>
            <HealthInfoCard label="SMTP-levering" tooltip="Krever faktisk leveringsbekreftelse. Konfigurert SMTP er ikke et leveringsbevis.">
              {health.smtp_delivery_verified === true ? "Verifisert" : "Ikke verifisert"}
            </HealthInfoCard>

            <HealthInfoCard label="Diskbruk" tooltip="Brukt diskplass på maskinen.">
              {health.disk_used_bytes !== null && health.disk_total_bytes !== null ? `${formatBytes(health.disk_used_bytes)} / ${formatBytes(health.disk_total_bytes)}` : "—"}
            </HealthInfoCard>
            <HealthInfoCard label="Ledig disk" tooltip="Ledig diskplass på maskinen.">
              {formatBytes(health.disk_free_bytes)}
            </HealthInfoCard>
            <HealthInfoCard label="Cache-størrelse" tooltip="Størrelse på lokal Nexus/Appliance-cache.">
              {formatBytes(health.cache_size_bytes)}
            </HealthInfoCard>
            <HealthInfoCard label="Feil/varsler siste 24t" tooltip="Antall registrerte feil og varsler siste døgn.">
              <div className="health-card__pair-grid">
                <div className="health-card__pair">
                  <span>Feil</span>
                  <strong>{health.errors_last_24h.toLocaleString("nb-NO")}</strong>
                </div>
                <div className="health-card__pair">
                  <span>Varsler</span>
                  <strong>{health.warnings_last_24h.toLocaleString("nb-NO")}</strong>
                </div>
              </div>
            </HealthInfoCard>
          </div>
        </section>
      )}
    </div>
  );
}

function HealthInfoCard({ label, tooltip, children }: { label: string; tooltip: string; children: ReactNode }) {
  const tooltipId = useId();

  return (
    <article className="detail-card health-card" tabIndex={0} role="group" aria-describedby={tooltipId}>
      <span className="health-card__label">{label}</span>
      <div className="health-card__value">{children}</div>
      <div className="health-card__tooltip" id={tooltipId} role="tooltip">
        {tooltip}
      </div>
    </article>
  );
}
