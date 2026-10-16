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
