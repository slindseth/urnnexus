/* Read-only verification. Optional representative API must be an isolated
   Nexus backend using structured fixture history and a held test worker lock. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const base = process.env.NEXUS_VERIFY_URL || "http://127.0.0.1:5176";
const representative = process.env.NEXUS_VERIFY_REPRESENTATIVE_API;
const artifacts =
  process.env.NEXUS_VERIFY_ARTIFACTS ||
  path.resolve("browser-artifacts/activity");
(async () => {
  fs.mkdirSync(artifacts, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1050 },
  });
  const page = await context.newPage();
  const errors = [],
    mutations = [],
    checks = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await context.route("**/*", async (route) => {
    const request = route.request();
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      mutations.push(request.method() + " " + request.url());
      return route.abort();
    }
    if (!request.url().startsWith(base) && !request.url().startsWith("data:"))
      return route.abort();
    return route.continue();
  });
  const json = async (url) => {
    const r = await context.request.get(url);
    assert.equal(r.status(), 200, url);
    return r.json();
  };
  try {
    const logs = await json(base + "/api/activity/logs");
    assert(
      logs.entries.some(
        (e) => e.origin === "operational" && e.level === "WARNING",
      ),
    );
    await page.goto(base + "/activity");
    await page.locator(".activity-log-row--warning").first().waitFor();
    assert(
      (
        await page.locator(".activity-log-row__time").first().innerText()
      ).includes("UTC"),
    );
    assert(
      !(await page.locator(".activity-status").innerText()).includes(
        "Running OCR",
      ),
    );
    const liveIds = await page
      .locator(".activity-log-row")
      .evaluateAll((rows) => rows.map((row) => row.dataset.eventId));
    await page.waitForResponse(
      (r) => r.url().includes("/api/activity/logs") && r.status() === 200,
    );
    assert.deepEqual(
      await page
        .locator(".activity-log-row")
        .evaluateAll((rows) => rows.map((row) => row.dataset.eventId)),
      liveIds,
    );
    await page
      .locator(".activity-log-row .activity-evidence summary")
      .first()
      .click();
    await page.screenshot({
      path: path.join(artifacts, "operational-desktop.png"),
      fullPage: true,
    });
    checks.push(
      "existing operational warnings keep dated occurrences and stable IDs after polling; historical completeness unknown",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: path.join(artifacts, "operational-narrow.png"),
      fullPage: true,
    });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      "operational mobile overflow",
    );
    await page.setViewportSize({ width: 1440, height: 1050 });
    await page.goto(base + "/projects/Citypassasjen/reports");
    await page
      .getByRole("region", { name: "Synkronisering og analysedekning" })
      .waitFor();
    const coverage = page.getByRole("region", {
      name: "Synkronisering og analysedekning",
    });
    await coverage.getByText(/Historiske parser- og filbegrensninger/).click();
    assert((await coverage.innerText()).includes("AG47-49 Sammenstilt.smc"));
    await page.screenshot({
      path: path.join(artifacts, "historical-smc-coverage.png"),
      fullPage: true,
    });
    checks.push(
      "actual Citypassasjen SMC limitation remains visible beside report access, independently of sync status",
    );

    if (representative) {
      await page.route("**/api/**", async (route) => {
        assert.equal(route.request().method(), "GET");
        const original = new URL(route.request().url());
        const response = await route.fetch({
          url: representative + original.pathname + original.search,
        });
        await route.fulfill({ response });
      });
      const events = await json(representative + "/api/activity/logs");
      assert.equal(
        events.entries.filter(
          (e) => e.event_id === "warn-1" || e.event_id === "warn-2",
        ).length,
        2,
      );
      await page.goto(base + "/activity");
      await page.locator('[data-event-id="incomplete"]').first().waitFor();
      assert.equal(
        await page.locator('.activity-log-row[data-event-id^="warn-"]').count(),
        2,
      );
      assert.equal(
        await page
          .locator('.activity-log-row[data-event-id="test-failure"]')
          .count(),
        0,
      );
      assert(
        (await page.locator(".activity-log-list").innerText()).includes(
          "Sync completed with no changes",
        ),
      );
      const status = await json(representative + "/api/activity/status");
      assert.equal(status.project_name, "Prosjekt Æ");
      assert(status.job_id);
      assert(
        (await page.locator(".activity-status").innerText()).includes(
          status.job_id,
        ),
      );
      assert.equal(
        (await json(representative + "/api/sync/status")).sync_status,
        "incomplete",
      );
      await page
        .locator('.activity-log-row[data-event-id="warn-1"] summary')
        .click();
      await page.screenshot({
        path: path.join(artifacts, "representative-operational.png"),
        fullPage: true,
      });
      const ids = await page
        .locator(".activity-log-row")
        .evaluateAll((rows) => rows.map((row) => row.dataset.eventId));
      await page.waitForResponse(
        (r) => r.url().includes("/api/activity/logs") && r.status() === 200,
      );
      assert.deepEqual(
        await page
          .locator(".activity-log-row")
          .evaluateAll((rows) => rows.map((row) => row.dataset.eventId)),
        ids,
      );
      await page
        .getByRole("combobox", { name: "Aktivitetsopphav", exact: true })
        .selectOption("test");
      await page
        .locator('.activity-log-row[data-event-id="test-failure"]')
        .waitFor();
      assert.equal(
        await page.locator('.activity-log-row[data-event-id^="warn-"]').count(),
        0,
      );
      await page.screenshot({
        path: path.join(artifacts, "representative-test.png"),
        fullPage: true,
      });
      await page
        .getByRole("combobox", { name: "Aktivitetsopphav", exact: true })
        .selectOption("unknown");
      await page
        .locator('.activity-log-row[data-event-id="undated"]')
        .waitFor();
      assert(
        (
          await page
            .locator(
              '.activity-log-row[data-event-id="undated"] .activity-log-row__time',
            )
            .innerText()
        ).includes("Udatert"),
      );
      await page.reload();
      assert(
        (await page.locator(".activity-status").innerText()).includes(
          status.job_id,
        ),
      );
      const link = page.getByRole("link", {
        name: "Åpne aktivt prosjekt og jobb",
      });
      assert(
        (await link.getAttribute("href")).includes(
          encodeURIComponent(status.job_id),
        ),
      );
      await link.click();
      await page.getByText("Seksjoner vurdert", { exact: true }).waitFor();
      assert.equal(new URL(page.url()).searchParams.get("job"), status.job_id);
      await page
        .getByText("Manuell kontroll og referanser", { exact: true })
        .click();
      await page.getByText("modell.smc", { exact: true }).first().waitFor();
      await page.screenshot({
        path: path.join(artifacts, "representative-job-coverage.png"),
        fullPage: true,
      });
      const reports = (
        await json(
          representative +
            `/api/projects/${encodeURIComponent(status.project_name)}/memory/jobs/${encodeURIComponent(status.job_id)}/reports`,
        )
      ).reports;
      assert(reports.length);
      assert.equal(
        (
          await context.request.get(representative + reports[0].download_url)
        ).status(),
        200,
      );
      checks.push(
        "structured incomplete/unchanged results; two distinct warnings; separate test/unknown views; undated marker; stable polling and refresh; durable active job link; SMC manual coverage and report download",
      );
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(mutations, []);
    fs.writeFileSync(
      path.join(artifacts, "result.json"),
      JSON.stringify(
        {
          checks,
          javascriptErrors: errors,
          mutations,
          screenshots: fs
            .readdirSync(artifacts)
            .filter((f) => f.endsWith(".png")),
        },
        null,
        2,
      ),
    );
    console.log(
      JSON.stringify(
        {
          checks,
          javascriptErrors: errors.length,
          mutations: mutations.length,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
