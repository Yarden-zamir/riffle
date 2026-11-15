import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { createServer } from "vite";

// No new browser dependency: use an existing Playwright installation, as in sourceEditor.browser.mjs.
test("shared profile page", { skip: !process.env.PLAYWRIGHT_MODULE, timeout: 60_000 }, async (t) => {
  const { chromium } = await import(process.env.PLAYWRIGHT_MODULE);
  const server = await createServer({ server: { host: "127.0.0.1", port: 0 } });
  await server.listen();
  t.after(() => server.close());
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  const owner = "anon:test-reader";
  const sources = Array.from({ length: 44 }, (_, index) => ({
    name: `Public feed ${index + 1}`, plugin: "rss-atom", config: { url: `https://example.com/feed/${index + 1}` },
  }));

  async function setup(width, colorScheme, { existing = false, missing = false } = {}) {
    const page = await browser.newPage({ viewport: { width, height: width < 600 ? 844 : 900 }, colorScheme });
    t.after(() => page.close());
    page.setDefaultTimeout(5000);
    const calls = [];
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("http://127.0.0.1:8000/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const method = request.method();
      const send = (value, status = 200) => route.fulfill({ status, contentType: "application/json", headers: {
        "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true", "Access-Control-Allow-Headers": "*",
      }, body: status === 204 ? "" : JSON.stringify(value) });
      if (method === "OPTIONS") return send({}, 204);
      calls.push({ path, method, body: request.postDataJSON() });
      if (path === "/me") return send({ id: owner, authenticated: false, login: null, auth_enabled: true, anonymous_has_data: false });
      assert.equal(request.headers()["x-riffle-owner"], owner);
      if (path === "/profiles") return send(existing ? [{ name: "dev", source_count: 1 }] : []);
      if (path === "/shares/demo-share-token") return send(missing ? {} : { name: "dev", shared_by: "Yarden-zamir", sources }, missing ? 404 : 200);
      assert.equal(path, "/shares/demo-share-token/import");
      assert.equal(method, "POST");
      assert.equal(request.headers()["x-riffle-request"], "1");
      return send({ profile: request.postDataJSON().name, sources: 44, changes: 0, skipped: 0 });
    });
    await page.goto(`${origin}/share/demo-share-token`);
    t.after(() => assert.deepEqual(errors, []));
    return { page, calls };
  }

  for (const width of [1280, 390, 320]) {
    for (const scheme of ["light", "dark"]) {
      await t.test(`${width}px ${scheme}: import first, collapsed sources, explicit import`, async () => {
        const { page, calls } = await setup(width, scheme);
        const button = page.getByRole("button", { name: "Import 44 sources", exact: true });
        await button.waitFor();
        const summary = page.locator("summary");
        assert.equal(await summary.textContent(), "Show 44 sources");
        assert.equal(await page.locator("details").evaluate((element) => element.open), false);
        assert.equal(await page.locator("details ul").isVisible(), false);
        const buttonBox = await button.boundingBox();
        const summaryBox = await summary.boundingBox();
        assert.ok(buttonBox.y < summaryBox.y, "Import precedes the source list");
        assert.ok(buttonBox.y + buttonBox.height < 844, "Import is visible without scrolling on a phone");
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        assert.equal(calls.some((call) => call.method !== "GET"), false, "Opening a share never imports it");
        if (process.env.SHARE_SCREENSHOTS && width !== 320) {
          await mkdir(process.env.SHARE_SCREENSHOTS, { recursive: true });
          await page.evaluate(() => document.fonts.ready);
          await page.screenshot({ path: join(process.env.SHARE_SCREENSHOTS, `${width === 1280 ? "desktop" : "phone"}-${scheme}.png`), fullPage: true });
        }
        await summary.focus();
        await page.keyboard.press("Enter");
        assert.equal(await page.locator("details ul").isVisible(), true);
        assert.equal(await page.locator("details li").count(), 44);
        assert.equal(await page.locator("details li").first().textContent(), "Public feed 1example.com");
        await page.keyboard.press("Enter");
        assert.equal(await page.locator("details ul").isVisible(), false);
        await button.click();
        await page.getByRole("link", { name: "Open your feed", exact: true }).waitFor();
        assert.deepEqual(calls.filter((call) => call.method === "POST"), [
          { path: "/shares/demo-share-token/import", method: "POST", body: { name: "dev" } },
        ]);
      });
    }
  }

  await t.test("existing profile naming and joining stay available above the list", async () => {
    const { page, calls } = await setup(390, "light", { existing: true });
    const name = page.getByLabel("Import into the profile");
    await name.waitFor();
    assert.equal(await name.inputValue(), "dev (shared)");
    await name.fill("dev");
    await page.getByText("You already have this profile.", { exact: false }).waitFor();
    assert.equal(calls.some((call) => call.method !== "GET"), false);
  });

  await t.test("unknown or revoked links keep the not-found message and no import", async () => {
    const { page, calls } = await setup(390, "dark", { missing: true });
    await page.getByText("This share link is unknown, or its owner stopped sharing the profile.", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: /Import/ }).count(), 0);
    assert.equal(await page.locator("details").count(), 0);
    assert.equal(calls.some((call) => call.method !== "GET"), false);
  });
});
