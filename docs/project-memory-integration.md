# Prosjektminne i Nexus

Nexus viser lagrede resultater fra appliance og bestiller dokumenterte CLI-operasjoner. Appliance eier inventar, parser/OCR, indeks, analyser, funn, evidens, jobber og Word-rapporter. Nexus har ingen egen analysedatabase og utfører ingen faglig sammenslåing av funn.

## Brukerflyt

1. Velg prosjekt i **Analyser** eller **Prosjekter**, og åpne **Funn og kilder**.
2. Lagret jobb lastes uten analyse. Velg en eldre jobb i «Jobb og snapshot». En eksplisitt valgt jobb beholdes i URL-en (`?job=job:…`) og kan åpnes igjen etter restart.
3. Se faktisk stadium, status og dekning. `partial` betyr at gjennomgangen har begrensninger selv om en Word-rapport finnes. Åpne manuelle enheter og referanser for gjenstående kontroll. Å åpne en kilde endrer ingen kontrollstatus.
4. Utvid et samlet funn for konklusjon, usikkerhet, anbefalt avklaring, originalforslag og kilder. Seks kilder lastes først; resten kan åpnes med «Vis flere kilder». Avviste forslag vises separat. Kildebekreftelse er en maskinvurdering, ikke menneskelig fagkontroll.
5. Last ned den lagrede `.docx`-rapporten, eller åpne lokal tekstvisning. Delvise og historiske rapporter kan fortsatt åpnes. Andre rapportfiler vises separat som eldre resultater uten ny verifikasjonsstatus.
6. **Oppdater analyse** starter en inkrementell gjennomgang. **Full reanalyse** krever et eget valg i dialogen. **Gjenoppta samme jobb** finnes for feilet/stoppet/avbrutt jobb når ingen arbeider kjører. **Be om stopp** lagrer en kooperativ forespørsel; et aktivt kall kan fullføres først.

Arbeidet starter bare fra et aktivt analysevalg. Direkte prosjektgjennomgang sender ingen e-post og laster ikke opp rapporter. Det eksisterende OneDrive-synkvalget er en separat flyt.

## Konfigurasjon og eksakt lokal oppstart

Bruk appliance-versjonen beskrevet i [appliance-kontrakten](../../appliance/docs/project-memory-nexus-contract.md), med databaseversjon 2 og et fungerende Python-miljø på `APPLIANCE_ROOT/.venv/bin/python`. Nexus bruker dette miljøet til CLI-kall. Ingen ny backend-tjeneste i appliance er nødvendig.

Automatisk funn av prosjekter og standard state fungerer fortsatt. For eksplisitt tilkobling av ferdige lokale eller OneDrive-jobber, opprett en serverlokal JSON-fil, for eksempel `/home/anbudklient/urn-nexus-web/.nexus-runtime/projects.json`:

```json
{
  "projects": [
    {
      "name": "Mitt prosjekt",
      "project_root": "/absolutt/sti/til/Mitt prosjekt",
      "state_root": "/absolutt/sti/til/state/project-memory/PROSJEKTHASH",
      "project_id": "project:ID_FRA_APPLIANCE",
      "environment": {
        "APPLIANCE_MEMORY_MODEL": "gpt-5.5",
        "APPLIANCE_MEMORY_VERIFICATION_MODEL": "gpt-5.5"
      }
    }
  ]
}
```

Bruk faktisk rot, state og ID fra appliance. Ikke konstruer en ny ID for et eksisterende prosjekt. `state_root` og `project_id` kan utelates for et nytt prosjekt som skal bruke `PROJECT_ROOT/.appliance-memory`. Miljøverdier her må begynne med `APPLIANCE_MEMORY_`; nettleseren kan ikke sende stier, modeller eller miljøinnstillinger. Lagre hemmeligheter i servermiljøet, aldri i frontend eller registereksemplet. Gjenopptak krever de samme prosesseringsinnstillingene som den opprinnelige jobben, også tokenbudsjett, embeddingmodus og modellversjon.

Terminal 1:

```bash
cd /home/anbudklient/urn-nexus-web
export URN_NEXUS_APPLIANCE_ROOT=/home/anbudklient/appliance
export URN_NEXUS_MEMORY_CLI_ROOT=/home/anbudklient/appliance
export URN_NEXUS_MEMORY_PROJECTS_FILE=/home/anbudklient/urn-nexus-web/.nexus-runtime/projects.json
export URN_NEXUS_MEMORY_RUNTIME_ROOT=/home/anbudklient/urn-nexus-web/.nexus-runtime
export URN_NEXUS_MEMORY_ACTIONS_ENABLED=true
export URN_NEXUS_MEMORY_PROVIDER=openai
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd /home/anbudklient/urn-nexus-web/frontend
npm ci
VITE_NEXUS_AUTO_SYNC=false VITE_BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

Åpne `http://127.0.0.1:5173`. `VITE_NEXUS_AUTO_SYNC=false` slår av den eksisterende daglige synken ved åpning, nyttig ved lokal verifikasjon. Standard er fortsatt daglig sync-only; analyse starter aldri automatisk. Vite-variabler må settes før oppstart/build. For bare lesing, sett `URN_NEXUS_MEMORY_ACTIONS_ENABLED=false`. For isolerte tester kan `URN_NEXUS_MEMORY_PROVIDER=fixture` og `APPLIANCE_MEMORY_EMBEDDING_MODE=disabled` brukes; denne leverandøren foretar ingen faglig modellvurdering.

Nexus og CLI må kunne lese state og immutable `objects/`. Analyse trenger i tillegg skrivetilgang til prosjektets `Kommentarer`, state og Nexus sin runtime-mappe. Arbeiderloggene ligger privat i runtime-mappen. Behold samme runtime-mappe ved restart: en lås arvet av arbeiderprosessen hindrer dobbeltstart også når Nexus-backend starter på nytt. Ingen tjeneste eller eksisterende produksjonsprosess er omstartet av denne integrasjonen.

## Grensesnitt og avgrensning

Browser → Nexus: `/api/projects/{project_name}/memory`.

| HTTP | Operasjon |
| --- | --- |
| GET `/jobs?after=OFFSET` | Siste jobber, 50 om gangen, faktiske ID-er |
| GET `/jobs/{job}` | CLI `status`, arbeiderlås, historisk snapshot og avgrenset kildeintegritet |
| POST `/run` | `{ "mode": "incremental\|full\|resume", "job_id": "…" }`; jobb-ID kun ved resume |
| POST `/jobs/{job}/cancel` | CLI `cancel`, kooperativ stopp |
| GET `/jobs/{job}/findings`, `/events`, `/manual-review`, `/references` | Dokumenterte CLI-leseoperasjoner, paginert |
| GET `/jobs/{job}/inventory`, `/cache-events`, `/retrieval-audit` | Dokumenterte detaljoperasjoner, tilgjengelig for drift |
| GET `/jobs/{job}/evidence/{evidence}` | CLI `evidence`, lokasjon, eksakt utdrag, usikkerhet og kildelenke |
| GET `/jobs/{job}/evidence/{evidence}/source` | Lagret kildeversjon med prosjekt-/jobbkontroll og hashkontroll |
| GET `/jobs/{job}/units/{unit}/source` | Lagret versjon for manuell enhet, avgrenset til snapshot |
| GET `/jobs/{job}/reports` | CLI `reports`, rapport-ID, hash og Nexus-lenker |
| GET `/jobs/{job}/reports/{report}/download`, `/preview` | Immutable DOCX eller lokal tekstvisning; ingen ekstern Office-visning |
| GET `/jobs/{job}/views` | Lagret sluttoversikt og 20 temaer om gangen |

POST krever `X-Nexus-Action: project-memory`. Dette er vern mot utilsiktede enkle skjemaforespørsler, **ikke brukerautentisering**. Gamle `/api/analysis/start` og `/api/analysis/run` delegerer nå til prosjektminne og returnerer 202, med valgt prosjekt og samme header. Gamle bulk-/e-postvalg videreføres ikke til arbeideren. Prosjektpanelet bruker de varige jobbene, ikke de gamle, prosesslokale analyseindikatorene.

Backend kjører `scripts/review_project.py` med `--state-root`, faktisk `--project-id` og `--job-id`. Full analyse legger til `--full`; resume bruker samme jobb-ID. Lesing bruker korte CLI-prosesser med timeout, ett sekund hurtigbuffer og paginering. Bare jobboversikt/status poller mens arbeid pågår. Store funn, temaer, kilder og historikk lastes separat.

Støttede read-only SQLite-spørringer (`mode=ro`, `query_only`) brukes til prosjekt-/jobbidentitet, nyeste jobb først, låser, versjons-/rapportoppslag og views; kontrakten har ingen egen CLI-listing for views eller kildenedlasting. Filtilgang må samsvare med både prosjekt, jobb og snapshot, ligge i state sin `objects/` og bestå SHA256-kontroll. Tilfeldige absolutte stier fra nettleseren aksepteres ikke. SQL skriver aldri arbeidsstatus. Ingen analyse, migrering, beslutninger, e-post eller Graph-opplasting utføres ved GET.

## Presise begrensninger

- Kontrakten har ingen handling for å løse en manuell parserenhet. Nexus tilbyr bare lesing og kildeåpning. `decision` er ikke en erstatning for en slik tilstandsovergang.
- Det finnes ingen read-only operasjon som inventerer nåværende fjernkilder. Nexus sammenligner inntil 100 kjente lokale kildefiler og 16 MiB per snapshot, med 30 sekunders buffer. Endret hash gir en tydelig utdatert-indikasjon; manglende/ukontrollerte filer gir «aktualitet ikke bekreftet». Nye filer, slettinger fra fjernkilden og fjernendringer krever synk og et nytt appliance-inventar. Nexus endrer ikke jobbstatusen for å vise dette.
- Flere rapportutgaver kan tilhøre én jobb. Kontrakten lagrer ikke hver rapportutgaves tidligere jobbstatus. Nexus viser valgt jobbs status og markerer jobbens gjeldende rapport-ID; eldre utgaver får ingen oppdiktet verifikasjonsstatus.
- `running` uten arbeiderlås kan være en avbrutt jobb. Nexus tilbyr gjenopptak; feil fra forskjellige prosesseringsinnstillinger må rettes i serverkonfigurasjonen.
- Microsoft-autentisering, ekstern opplasting og SMTP-levering er ikke bekreftet av prosjektminnetestene. Helse viser dem som **Ikke verifisert**. Eksisterende konfigurasjons-/cacheindikatorer er ikke tilkoblingsbevis.
- Nexus har fortsatt ingen egen bruker-/tenantautentisering. Referanser er avgrenset til prosjekt og jobb; autorisasjon for flere brukere må håndteres før eksponering utenfor et betrodd, autentisert miljø. Ingen ny ekstern publisering er gjort her.

## Verifikasjon

```bash
cd /home/anbudklient/urn-nexus-web
.venv/bin/python -m pytest tests/test_project_memory.py -q
.venv/bin/python -m pytest -q
cd frontend
npm test -- --reporter=dot
npm run build
```

CLI-kontraktstestene bruker ekte appliance CLI med `fixture`, deaktivert embedding og ingen OpenAI-nøkkel. Alle mutasjoner skjer i midlertidige Nexus-testprosjekter. `NEXUS_TEST_MEMORY_CLI_ROOT` kan overstyre appliance-stien; disse integrasjonstestene hoppes over hvis CLI ikke er installert. Samlede funn/evidens i transporttesten er uttrykkelige syntetiske kontraktsdata, ikke et nytt semantisk kvalitetsmål.

Se [verifikasjonsresultat](project-memory-verification.md) for faktisk kjørte kontroller og avgrensninger.

## Aktivitet, sync-fullføring og kildedekning

Aktivitetsadapteren følger [appliance-kontrakten](../../appliance/docs/project-memory-nexus-contract.md), avsnittet «Sync-fullføring og hendelsesproveniens». Pagination-rettingen og dens avgrensede Graph-kontroll er beskrevet i [appliance-verifikasjonen](../../appliance/docs/project-memory-verification.md). Nexus endrer ikke appliance-kode eller prosjektminnets analyse-/rapportflyt.

`/api/sync/status` og startsvaret har additive `sync_status`, `enumeration_complete` og `project_results`. Monitoren bruker eksplisitt aggregate- og prosjektresultat. Et ufullstendig prosjekt/enumerering overstyrer påstått suksess. Manglende fullføringsbevis gir `unknown`; returkode 0, null nedlastinger, `phase=completed`, gammel rapport og `skipped_no_changes` er utilstrekkelig. Analyse-/leveringsfeil endrer ikke en eksplisitt komplett sync til mislykket filsynk. «Completed with no changes» krever komplett sync og kjente null endringer; sletting/omdøping teller også. Bare dokumentert komplett kildesnapshot kan oppdatere helsens `last_synced_at`.

Aktivitetssvarene beholder `event_id`, `source_event_id`, `run_id`, `job_id`, kilde, alvorlighet, miljø, transport, synlighet og rå historikk i `raw`. `timestamp` er nullable. Dato og eksplisitt UTC vises; opprinnelig tidsstempel ligger også i råposten. Manglende/ugyldig dato eller tidssone blir **Udatert**, aldri dagens klokkeslett. Identitetsløse JSONL-poster får en deterministisk ID fra filplassering og byteposisjon; separate identiske forekomster bevares. Polling erstatter visningen med et nytt snapshot. Loggvisningens «Tøm visning» skjuler bare innleste ID-er i nettleserminnet.

`event_records`, `source_ingestion_events` og `processing_records` leses som eksplisitte hendelser med egne tider. Generiske historikksammendrag lager ingen OCR-, rapport-, opplastings- eller e-posthendelser. Eldre fullføringspåstander uten syncbevis merkes som historiske påstander med ukjent fullføring; originalmeldingen beholdes i `raw`. En historisk feil er ikke merket «aktiv feil».

`/api/activity/status` har `running` og bruker levende prosess-/arbeiderlås. Prosjektminnets aktive jobb må også være den nyeste lagrede `running`-jobben for samme prosjekt; faktisk jobb-ID og prosjekt-ID leses fra den eksisterende skrivebeskyttede databasen. URL til gjennomgang bruker samme jobb-ID. Arbeiderlås uten ny jobbidentitet gir ingen oppdiktet ID. Hendelser fra inntil fem nyeste jobber per prosjekt leses fra native eventrader (inntil 100 per jobb), med stabil prosjekt/jobb/sekvens-identitet. Ingen analyse eller migrering startes. Legacy synklåser kontrolleres, men slettes ikke ved statuslesing; appliance eier oppryddingen.

Drift, test og ukjent opphav har egne valg. `environment=test`, `transport=test_transport` eller en eksplisitt pytest-kildesti dokumenterer testopphav. `environment=production` dokumenterer drift. Prosjektnavn og meldingsordlyd bestemmer aldri opphav. Native minnehendelser og eldre poster uten miljø beholdes som ukjente; dagens servermiljø brukes ikke til å ettermerke dem. Grensene 40 hendelser, 10 feil og 160 logglinjer gjelder per opphav, slik at tester ikke fortrenger driftsvarsler fra det innleste vinduet. JSONL-lesing er avgrenset til 120 siste poster per konfigurert fil.

Standard aktivitet leser kun `outputs/<konfigurert selskapsrot>/history.jsonl`, Nexus-journalen og synkhistorikker under konfigurerte runtime-røtter; den skanner ikke alle `outputs`-mapper etter testhistorikk. Drift kan sette en eksplisitt JSON-liste over tillatte historikkfiler:

```bash
export URN_NEXUS_ACTIVITY_HISTORY_PATHS='["/absolute/operational/onedrive_sync_history.jsonl"]'
```

Tom liste `[]` slår av appliance-historikk i aktivitetsfeeden, men ikke den separate Nexus-journalen eller prosjektminnets native hendelser. `URN_NEXUS_ENVIRONMENT=production|test|development` kan angi miljø for **nye Nexus-journalposter**; uten innstilling er miljø ukjent. Eksisterende filer ettermerkes ikke.

Prosjektdetaljer har `sync_coverage`: eksplisitt sync-/enumereringsstatus, siste dokumenterte kildesnapshot, separat analysestatus, policyutelatelser og historiske parser-/filbegrensninger. Denne projeksjonen leser hele det konfigurerte arkivet med filsignaturbuffer, også når en SMC-begrensning er eldre enn aktivitetstailen. Prosjekttilknytningen er eksakt. Begrensninger med samme melding kan grupperes med antall, første/siste tid og utvidbare forekomster. Arkivbegrensninger er observasjoner, ikke bevis på at samme fil fremdeles finnes. Native manuelle enheter og uleselige snapshot-manifestposter vises i valgt prosjektjobb. Delvise Word-rapporter og kildeåpning beholdes. Ingen «løst»-handling er lagt til.

Manglende produsentmetadata kan ikke rekonstrueres: eldre syncinnslag mangler ofte fullføringsfelt og event-ID; native minnehendelser mangler miljø/transport. Opprinnelige Graph-responser finnes ikke for hver gammel advarsel. En ukjent historisk sync er derfor ikke etterkonvertert til komplett eller feil. Ved flere samtidige prosjektarbeidere viser statuskortet én aktiv prosjektjobb; hendelsesdetaljene beholder hver jobbs identitet.
