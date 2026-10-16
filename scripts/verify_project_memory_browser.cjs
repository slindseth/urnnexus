/* Read-only browser verification by default. Set NEXUS_VERIFY_OFFLINE_PROJECT
   only when the backend uses provider=fixture with external delivery disabled.
   Requires Playwright in NODE_PATH or installed as a development tool. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.NEXUS_VERIFY_URL || 'http://127.0.0.1:5174';
const project = process.env.NEXUS_VERIFY_PROJECT || 'OperativKontroll';
const artifacts = process.env.NEXUS_VERIFY_ARTIFACTS || path.resolve('browser-artifacts');
const memory = `/api/projects/${encodeURIComponent(project)}/memory`;
(async () => {
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
  const page = await context.newPage();
  const errors = [], posts = [], outside = [], fontRequests = [], checks = [];
  context.on('page', p => p.on('pageerror', e => errors.push(e.message)));
  page.on('pageerror', e => errors.push(e.message));
  context.on('request', request => {
    if (request.method() === 'POST') posts.push(request.url());
    if (!request.url().startsWith(base) && !request.url().startsWith('data:')) {
      if (['fonts.googleapis.com', 'fonts.gstatic.com'].includes(new URL(request.url()).hostname)) fontRequests.push(request.url());
      else outside.push(request.url());
    }
  });
  const json = async url => { const r = await context.request.get(base + url); assert.equal(r.status(), 200, url); return r.json(); };
  try {
    const listing = await json(`${memory}/jobs`);
    const latest = listing.jobs[0]; assert(latest);
    const prefix = `${memory}/jobs/${encodeURIComponent(latest.id)}`;
    const status = await json(prefix);
    const findings = (await json(prefix + '/findings')).findings.filter(f => f.verification.supported);
    await page.goto(`${base}/analysis`);
    await page.getByRole('heading', { name: 'Velg prosjekt' }).waitFor();
    const row = page.getByRole('row').filter({ hasText: project });
    await row.getByRole('button', { name: 'Analyser', exact: true }).click();
    await page.getByText('Seksjoner vurdert', { exact: true }).waitFor();
    await page.waitForURL(url => url.searchParams.get('job') === latest.id);
    await page.locator('.memory-finding').first().waitFor();
    assert.equal(await page.locator('.memory-finding').count(), findings.length);
    assert((await page.locator('.memory-counts').innerText()).includes(String(status.job.native_units)));
    assert((await page.locator('.memory-panel').innerText()).includes('Delvis gjennomgått'));
    checks.push('project selection, persisted job URL, actual counts, consolidated finding count, partial status');
    await page.reload(); await page.locator('.memory-finding').first().waitFor();
    assert.equal(new URL(page.url()).searchParams.get('job'), latest.id);
    assert.equal(posts.length, 0); checks.push('reload reconnects; opening performs no POST/analysis');
    const first = page.locator('.memory-finding').first(); await first.locator(':scope > summary').click();
    await first.locator('.memory-evidence h5').first().waitFor();
    const firstData = findings[0];
    while (await first.getByRole('button', { name: /Vis flere kilder/ }).count()) {
      await first.getByRole('button', { name: /Vis flere kilder/ }).click();
    }
    await page.waitForFunction(n => document.querySelectorAll('.memory-finding[open] .memory-evidence h5').length === n, firstData.evidence.length);
    const citation = await json(`${prefix}/evidence/${encodeURIComponent(firstData.evidence[0])}`);
    const source = await context.request.get(base + citation.source_url);
    assert.equal(source.status(), 200); assert.equal(crypto.createHash('sha256').update(await source.body()).digest('hex'), citation.source_hash);
    const [sourceDownload] = await Promise.all([page.waitForEvent('download'), first.getByRole('link', { name: 'Åpne lagret kildeversjon' }).first().click()]);
    assert(await sourceDownload.path());
    checks.push('all consolidated citations expand; source download matches immutable version SHA256');
    await page.getByText('Manuell kontroll og referanser', { exact: true }).click();
    await page.getByRole('link', { name: 'Åpne denne kildeversjonen' }).first().waitFor();
    const gapsBefore = await json(prefix + '/manual-review');
    const gap = await context.request.get(base + gapsBefore.units[0].source_url); assert.equal(gap.status(), 200);
    const gapsAfter = await json(prefix + '/manual-review'); assert.deepEqual(gapsAfter, gapsBefore);
    const reports = (await json(prefix + '/reports')).reports; assert(reports.length);
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Last ned Word', exact: true }).first().click()]);
    const downloadPath = path.join(artifacts, 'partial-report.docx'); await download.saveAs(downloadPath);
    assert.equal(crypto.createHash('sha256').update(fs.readFileSync(downloadPath)).digest('hex'), reports[0].hash);
    const [preview] = await Promise.all([page.waitForEvent('popup'), page.getByRole('link', { name: 'Forhåndsvis tekst', exact: true }).first().click()]);
    await preview.waitForLoadState(); assert((await preview.locator('body').innerText()).includes('Tekstvisning')); assert(preview.url().startsWith(base)); await preview.close();
    checks.push('partial Word report download/preview; manual source opening leaves review flags unchanged');
    await page.getByText('Prosjektoversikt og temaoppsummeringer', { exact: true }).click();
    await page.getByText('Prosjektoversikt', { exact: true }).click();
    await page.getByText('Kildeverifisert maskinoversikt', { exact: false }).waitFor();
    checks.push('persisted verified overview and topic summaries');
    await page.getByRole('button', { name: 'Full reanalyse …', exact: true }).click();
    await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape');
    await page.getByRole('dialog').waitFor({ state: 'hidden' }); assert.equal(posts.length, 0);
    await page.screenshot({ path: path.join(artifacts, 'memory-desktop-expanded.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(artifacts, 'memory-narrow-top.png') });
    await page.screenshot({ path: path.join(artifacts, 'memory-narrow-expanded.png'), fullPage: true });
    await page.locator('.memory-evidence').first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(artifacts, 'memory-narrow-source.png') });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'horizontal overflow at 390px');
    checks.push('desktop and 390px layout; full-analysis dialog keyboard cancellation');
    if (listing.jobs.length > 1) {
      const old = listing.jobs[listing.jobs.length - 1];
      await page.getByLabel('Jobb og snapshot').selectOption(old.id);
      await page.getByText('Historisk snapshot.', { exact: false }).waitFor();
      await page.getByText('Kildegrunnlaget er endret.', { exact: false }).waitFor();
      await page.reload(); await page.getByText('Historisk snapshot.', { exact: false }).waitFor();
      assert.equal(new URL(page.url()).searchParams.get('job'), old.id);
      await page.getByRole('tab', { name: 'Rapporter', exact: true }).click();
      assert.equal(new URL(page.url()).searchParams.get('job'), old.id);
      checks.push('previous snapshot stays selected across refresh and tab navigation and shows revised-source warning');
    }
    await page.goto(`${base}/projects/${encodeURIComponent(project)}/reports`);
    await page.getByRole('heading', { name: 'Andre rapportfiler og eldre rapporter' }).waitFor();
    const legacy = await json(`/api/projects/${encodeURIComponent(project)}/reports`); assert(legacy.reports.length);
    assert.equal((await context.request.get(base + legacy.reports[0].download_url)).status(), 200);
    await page.goto(base + '/health'); await page.getByRole('heading', { name: 'Helse', exact: true }).waitFor();
    await page.getByText('Ikke verifisert', { exact: true }).first().waitFor(); assert.equal(await page.getByText('Ikke verifisert', { exact: true }).count(), 3);
    checks.push('legacy report download; authentication/upload/SMTP explicitly unverified');
    await page.route('**/memory/jobs?after=*', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 'memory_cli_unavailable', detail: 'Test: arbeider utilgjengelig. Kontroller CLI-sti.' }) }));
    await page.goto(`${base}/projects/${encodeURIComponent(project)}/review`);
    await page.getByText('Test: arbeider utilgjengelig. Kontroller CLI-sti.', { exact: false }).waitFor();
    assert.equal(await page.getByText('Laster lagret prosjektgjennomgang …', { exact: true }).count(), 0);
    await page.unroute('**/memory/jobs?after=*'); checks.push('unavailable appliance is actionable, without indefinite spinner');
    const offline = process.env.NEXUS_VERIFY_OFFLINE_PROJECT;
    if (offline) {
      await page.goto(`${base}/projects/${encodeURIComponent(offline)}/review`);
      await page.getByText('Seksjoner vurdert', { exact: true }).waitFor();
      const resume = page.getByRole('button', { name: 'Gjenoppta samme jobb', exact: true });
      if (await resume.count()) {
        const before = new URL(page.url()).searchParams.get('job');
        await resume.click(); await page.getByText('Starter arbeider …', { exact: true }).waitFor({ state: 'hidden', timeout: 20000 });
        assert.equal(new URL(page.url()).searchParams.get('job'), before);
        await page.getByText('Testkjøring uten modellvurdering.', { exact: false }).waitFor();
        checks.push('real offline CLI resumes the same durable job');
      }
      const before = new URL(page.url()).searchParams.get('job');
      await page.getByRole('button', { name: 'Oppdater analyse', exact: true }).click();
      await page.waitForURL(url => url.searchParams.get('job') && url.searchParams.get('job') !== before, { timeout: 20000 });
      await page.getByText('Testkjøring uten modellvurdering.', { exact: false }).waitFor();
      await page.reload(); await page.getByText('Testkjøring uten modellvurdering.', { exact: false }).waitFor();
      checks.push('real offline CLI incremental run, actual new job ID and reconnection');
    }
    assert.equal(errors.length, 0, errors.join('\n')); assert.equal(outside.length, 0, outside.join('\n'));
    fs.writeFileSync(path.join(artifacts, 'memory-browser-result.json'), JSON.stringify({ base, project, checks, pageErrors: errors, externalBrowserRequests: outside, existingFontAssetRequests: fontRequests.length, postRequests: posts }, null, 2));
    console.log(JSON.stringify({ checks, posts, errors, outside, existingFontAssetRequests: fontRequests.length }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
