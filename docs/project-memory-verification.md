# Verifisert Nexus-integrasjon

Verifikasjonen ble kjørt lokalt mot den ferdige appliance-kontrakten, med Nexus-endringer i denne repoen. Appliance ble bare lest. Ingen eksisterende produksjonstjeneste ble omstartet.

## Automatiske kontroller

| Kontroll | Resultat |
| --- | --- |
| `pytest tests/test_project_memory.py -q` | 8 bestått; ekte offline CLI, midlertidige prosjekter |
| `pytest -q` | 61 bestått, 2 tidligere eksisterende feil |
| `npm test -- --reporter=dot` | 109 bestått i 28 testfiler |
| `npm run build` | TypeScript og Vite-produksjonsbygg bestått |
| Ruff `--select F` for ny adapter, ruter, konfigurasjon og nye tester | Bestått |
| `git diff --check` | Bestått |

De to backend-feilene fantes før integrasjonen (før: 53 bestått, 2 feil). Begge leser faktisk lokal appliance-state og har utdaterte, faste forventninger:

- `test_projects_endpoint_lists_discovered_projects`: forventer 6 prosjekter, den lokale installasjonen har 7.
- `test_state_projects_discover_comment_documents_from_history_without_outputs_root_mixing`: forventer rapportversjon 6.0 for Bryn Skole, lokal state har 11.0.

Disse gamle dataforventningene og produksjonsdataene er ikke endret for å få grønn teststatus. Starlette gir dessuten en deprecation-advarsel om testklientens httpx; React-testene har eksisterende act/router/SSR-advarsler. Ingen av disse er gjort til nye produksjonsavhengigheter.

De nye backend-testene dekker varig jobbidentitet etter ny app-instans, ingen analyse ved GET, faktiske tellinger/status, konsoliderte funn med alle evidens-ID-er og originalforslag, uforanderlig kildeversjon etter kildeendring, delvis rapport, lokal tekstvisning, manuelle kildeenheter, uendret kontrollstatus ved åpning, eldre rapportnedlasting, historisk snapshot, manglende CLI/state, ukjent DB-skjema, negative sideparametre, feil prosjekt/jobb/evidens/rapport/enhet, sti utenfor `objects/`, feil hash, eksplisitt start/full/resume, lås på tvers av app-instans og faktisk kooperativ CLI-cancel. Cancel-testen simulerer liveness med en lås; den avbryter ikke et levende OpenAI-kall.

Frontend-testene dekker lagret jobbvalg, delvis/stale/feilet resultat, kildeuthenting ved åpning (6 + resten), utsatt lasting av temaenes kilder, ingen analyse ved sideåpning, nyttig feilvisning, sperret dobbeltstart, gjenopptak som fullfører raskt og oppstartslås før ny jobb-ID er skrevet. Den siste regresjonstesten ble lagt til etter at nettlesertesten avdekket at visningen kunne bli stående på gammel jobb.

## Faktisk nettleserflyt

Headless Chromium via Playwright, 1440 × 1050 og 390 × 844. Skjermbilder er også åpnet og inspisert. Isolert backend: `127.0.0.1:8011`; Vite: `127.0.0.1:5174`; automatisk OneDrive-synk deaktivert. Eksisterende porter 8000/5173 ble ikke berørt.

Den syntetiske, tidligere fullførte appliance-testen **OperativKontroll** ble kopiert inn i Nexus sin ignorerte `.nexus-runtime/verification/`. Prosjekt-, snapshot-, jobb-, funn-, evidens- og rapport-ID-er ble beholdt. Bare kopiens lokale prosjekt-/objektstier ble tilpasset kopien. Den semantiske jobben ble ikke analysert på nytt.

Faktisk kontrollert:

- Analyse → prosjektvalg → riktig nyeste jobb og snapshot; valgt ID skrives i URL-en.
- 8 samlede funn fra 13 kildeverifiserte forslag, med 4 vurderte seksjoner, 7 native enheter og 1 manuell enhet, lik appliance-status.
- Alle kilder for et utvidet samlet funn, eksakte utdrag/lokasjoner og kildeversjon. Faktisk kildefil ble lastet ned og SHA256 sammenlignet med evidenssvaret.
- Delvis Word-rapport lastet ned og hash sammenlignet med rapportreferansen; tekstforhåndsvisning åpnet i en lokal fane.
- Tre rapportutgaver i valgt jobb, gjeldende rapport-ID skilt fra tidligere utgaver.
- Manuell skannet kilde kan åpnes uten at kontrollstatus endres.
- Prosjektoversikt/temaer fra lagret view, inkludert kildeverifiseringsstatus og snapshot.
- Oppfrisking beholder jobb-ID. Eldre snapshot viser både historikk og faktisk endret lokal kilde. Valget beholdes også ved bytte til Rapport-fanen.
- Eldre rapportfil kan fortsatt lastes ned.
- Full reanalyse-dialog åpner og kan avbrytes med Escape uten POST.
- Ingen horisontal dokument-scroll ved 390 px etter utvidelse av funn, oversikt og manuelle referanser. Lange identifikatorer brytes innenfor panelet.
- Microsoft-innlogging, ekstern opplasting og SMTP-levering vises som «Ikke verifisert».
- Simulert HTTP 503 fra jobboversikten gir forklaring og nytt forsøk, og fjerner lastetilstanden.
- Ingen POST ved åpning, oppfrisking eller lesing. Ingen JavaScript-sidefeil. De eksisterende Google Fonts-ressursene lastes fortsatt; ingen andre eksterne browserforespørsler ble observert.

En separat, Nexus-eid **Prosjekt Æ** ble kjørt gjennom den virkelige `run --provider fixture`-kommandoen fra UI. En uttrykkelig simulert feilet jobb ble gjenopptatt med samme ID, og en inkrementell oppdatering fikk en ny faktisk jobb-ID som ble beholdt etter oppfrisking. Ingen live OpenAI-start var nødvendig. Dette verifiserer transport og styring; fixture-leverandøren vurderer ikke faglig kvalitet.

Arbeiderens brukstabell har **0** nye API-kall i offline-prosjektet. De to kopierte semantiske jobbene beholdt **79** og **77** registrerte kall. Ingen e-post- eller opplastingsoperasjon finnes i den brukte direkte gjennomgangskommandoen. Live Microsoft-, SMTP- og opplastingsfunksjoner er ikke validert av denne testen.

## Lokale bevis og gjentakelse

Ignorerte verifikasjonsfiler i `browser-artifacts/`:

- `memory-browser-result.json`: komplett flyt, inkludert to eksplisitte fixture-POST-er (resume/run).
- `final-readonly/memory-browser-result.json`: siste leseflyt, inkludert navigasjon mellom faner, **0 POST-er**.
- `final-readonly/memory-desktop-expanded.png`, `memory-narrow-top.png`, `memory-narrow-source.png`, `memory-narrow-expanded.png`.
- `partial-report.docx`: faktisk nedlastet rapport fra det syntetiske prosjektet.
- `memory-state-check.json`: brukstall og filkontroll. Alle **304** versjonerte/ikke-ignorerte appliance-filer samsvarte med SHA256-baseline tatt før Nexus-arbeidet.

Browser-skriptet kan kjøres mot et tilsvarende, ferdig testprosjekt:

```bash
cd /home/anbudklient/urn-nexus-web
NODE_PATH=/tmp/nexus-browser-check/node_modules \
  NEXUS_VERIFY_URL=http://127.0.0.1:5174 \
  NEXUS_VERIFY_PROJECT=OperativKontroll \
  node scripts/verify_project_memory_browser.cjs
```

Skriptet krever Playwright/Chromium som separat utviklingsverktøy; ingen produksjonsavhengighet ble lagt til. Det forventer en ferdig, delvis testjobb med funn, manuell enhet, kildeverifisert oversikt og rapporthistorikk. Bare sett `NEXUS_VERIFY_OFFLINE_PROJECT` når den registrerte prosjektkopien og backend faktisk er konfigurert med fixture-leverandør og levering av. Dette valget utfører eksplisitte analysehandlinger. Vanlig kjøring er lesende og tester at ingen POST sendes.

## Utestet og kontraktsgrenser

Produksjonsstart med OpenAI, gjenopptak under et levende API-kall, faktisk ekstern autentisering, rapportopplasting og SMTP-levering er ikke testet. Det er ingen støttet handling for å løse manuelle parserenheter eller read-only fjerninventar; se [integrasjonsdokumentasjonen](project-memory-integration.md#presise-begrensninger). Bruk eksisterende appliance-driftsrutiner for disse forholdene. Nexus lager ingen erstatningstilstand eller egne faglige funn.

## Aktivitetsrapportering — kontroll 15. oktober 2026 (America/New_York)

Nexus-arbeidet startet med oppdatert appliance-kontrakt og utfallet av pagination-rettingen. Appliance ble inspisert skrivebeskyttet. Følgende feil ble bekreftet i gjeldende Nexus-kode før retting:

- `_activity_candidates_from_history_payload` la til **Running OCR** ved generisk fullføring/rapporttelling, og utledet rapport-, opplastings- og e-posthendelser. Dette var fremdeles aktiv kode.
- `_monitor_sync_process` og refresh-ruten satte fullført fra returkode 0. Null `files_changed` ble til **Sync completed with no changes**, uten sync-/enumereringsbevis.
- Manglende historikktid ble erstattet med `datetime.now()`. Feeden viste bare klokkeslett. Deduplisering brukte tid/alvorlighet/prosjekt/komponent/melding, ikke hendelsesidentitet.
- Kilde og alvorlighet ble omformet; miljø, event-ID og kjørings-ID ble ikke bevart. Aktivitetslesingen gjenbrukte en bred rekursiv rapporthistorikkskanning.
- Gjeldende prosjekt kunne velges fra arkivet, og prosjektminnets varige aktive jobb ble ikke brukt i aktivitetsstatus.
- Browseren viste at frontend-avhengigheten også måtte rettes: eksplisitt `unknown` blokkerte oppstart, og daglig-sync godtok timestamp eller delstreng `complete` som suksess, inkludert `incomplete`.

Disse rapporteringsbanene er rettet. Kildenes gamle feilpåstander er bevart i rådetaljer og merket som historiske påstander med ukjent fullføring. Stale appliance-låser ignoreres nå uten å bli slettet ved GET. Prosjektminnets eksisterende start/resume/cancel-, kilde-, funn- og rapportintegrasjon er bevart.

| Kontroll | Resultat |
| --- | --- |
| `pytest tests/test_activity_reporting.py tests/test_project_memory.py tests/test_backend_sync_health.py -q` | **38 bestått** |
| Siste komplette `pytest -q` | **89 bestått, 2 eksisterende feil**; 13,66 s |
| `npm test -- --reporter=dot` | **116 bestått i 30 filer** |
| `npm run build` | TypeScript og Vite bestått |
| Ruff `--select F` på backend, ny verifikasjonsserver og nye/utvidede tester | Bestått |
| `git diff --check` | Bestått |

De to komplette-suitefeilene er de samme faste live-dataforventningene beskrevet over: 6 mot 7 prosjekter og Bryn Skole rapport 6.0 mot faktisk 11.0. Begge ble reprodusert ved å pakke ut uendret **0d6d183** i en separat nabomappe og kjøre de to testene der. Produksjonsdata og disse forventningene er ikke endret. Eksisterende Starlette/httpx- og React act/router/SSR-advarsler gjenstår.

De målrettede regresjonene beviser blant annet null-exit med ufullstendig resultat, motsigende aggregate/prosjektbevis, komplett uendret sync, sletting uten nedlasting, separat analysefeil, ingen oppdiktet OCR fra fullført historie, ekte nestet prosesseringshendelse med egen tid, undatert/naiv tid, stabile ID-er etter ny tail/refresh, deduplisert kilde-ID, separate identiske varsler, testtransport, prosjekt med «Testprosjekt»-navn i drift, ukjent opphav, avgrenset historikkilde, SMC/policydekning og uleselig manifest, tilgjengelig delrapport samt aktiv prosjektjobb med samme varige ID på tvers av app-instans og arbeiderlås.

### Browser → API → historikk/prosjektminne → visning

Chromium ble brukt på **1440 × 1050** og **390 × 844**. Lokale testporter var **8003/5176**. Automatisk sync var slått av i Vite; verifikasjonsserveren avviste alle muterende HTTP-metoder. Eksisterende produksjonstjenester ble ikke omstartet.

- Ekte operativ synkhistorikk: Graph-paginationvarsler er synlige i **Drift**, med opprinnelig dato, UTC, forekomst-ID og utvidbar dokumentasjon. Neste poll beholder nøyaktig samme innleste ID-liste. Ingen OCR eller prosjektjobb ble startet av arkivet. Eldre fullføring er ukjent, ikke ettergodkjent av den senere appliance-rettingen.
- Ekte Citypassasjen: **AG47-49 Sammenstilt.smc** finnes fortsatt i historiske dekningdetaljer på rapportsiden. Parser-/filbegrensninger og synkronisering vises separat.
- Isolert representativ historikk: ufullstendig sync med null nedlastinger forblir ufullstendig; komplett uendret prosjekt får riktig fullføring. To like Graph-varsler med ulike ID-er kan begge åpnes. Testfeilen vises bare i **Test**; ukjente/udaterte poster ligger i **Ukjent opphav** og merkes **Udatert**.
- Den midlertidige fixture-jobben hadde en eksplisitt simulert `running`-rad og holdt arbeiderlås. Riktig prosjekt og faktisk varig jobb-ID ble vist og beholdt etter reload. Lenken åpnet samme ID i gjennomgangen. Native SMC-enhet var synlig i manuell dekning; lagret Word-rapport var fortsatt tilgjengelig med HTTP 200.
- Skjermbildene ble åpnet og inspisert. Ingen horisontal dokument-scroll ved 390 px. **0 JavaScript-sidefeil, 0 muterende browserforespørsler**.

Den representative jobben opprettes med den ekte appliance-CLI-en i **fixture**-modus, deaktivert embedding og tom OpenAI-nøkkel, kun i en ny `/tmp/nexus-activity-browser-*`-mappe. Miljømarkøren `production` i de syntetiske historikkpostene er bevisst kontraktsdata for å teste Drift-valget, ikke reell driftsproveniens. Dette er ingen ny semantisk kvalitetsvurdering. Ingen OpenAI-analyse, e-post, kildeopplasting eller sletting av driftslogger ble initiert.

Maskinresultat og skjermbilder ligger i ignorerte `browser-artifacts/activity/`: `result.json`, `operational-desktop.png`, `operational-narrow.png`, `historical-smc-coverage.png`, `representative-operational.png`, `representative-test.png` og `representative-job-coverage.png`. `appliance-integrity.json` dokumenterer SHA256-kontroll av **204** appliance-kode-/dokumentasjonsfiler og eksisterende historikk-/loggfiler: **ingen endring**. En separat sluttkontroll av operative databaser, synk-state, historikk og logger er registrert i `operational-integrity.json`.

Gjenta lokalt (Playwright må allerede være tilgjengelig):

```bash
# Terminal 1, fra Nexus-roten. Kun midlertidig fixture skrives.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m uvicorn \
  scripts.serve_activity_verification:create_verification_app --factory \
  --host 127.0.0.1 --port 8003

# Terminal 2
cd frontend
VITE_NEXUS_AUTO_SYNC=false VITE_BACKEND_URL=http://127.0.0.1:8003 \
  npm run dev:vite -- --host 127.0.0.1 --port 5176

# Terminal 3, fra Nexus-roten
NODE_PATH=/path/to/node_modules \
  NEXUS_VERIFY_REPRESENTATIVE_API=http://127.0.0.1:8003/representative \
  node scripts/verify_activity_browser.cjs
```

Manglende produsentmetadata gjenstår som synlige begrensninger: eldre syncposter mangler eksplisitt fullføring, enkelte eldre hendelser mangler ID eller tids-/miljødata, og native minnehendelser mangler miljø/transport. Fullføring og driftsopphav kan derfor ikke etterkonstrueres. Midlertidige stier uten eksplisitt pytest-proveniens klassifiseres som ukjente. Ingen manuell parserenhet kan markeres løst gjennom den gjeldende appliance-kontrakten; Nexus tilbyr fortsatt bare lesing og kildeåpning.
