// Browser smoke test for the web UI. Run with tests/e2e/run.sh (builds and starts the server),
// or point BASE_URL at a running server: BASE_URL=http://127.0.0.1:8080 node tests/e2e/smoke.cjs
// Requires Playwright with a Chromium browser.
const { chromium } = require("playwright");
const assert = require("assert");

const BASE = process.env.BASE_URL || "http://127.0.0.1:8080";
const TABS = ["Build", "Analysis", "Simulation", "Compare", "Saved Builds", "Heroes", "Patch Notes", "Settings"];

async function watch(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push("page error: " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push("console: " + m.text());
  });
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 400) errors.push(`HTTP ${r.status()} ${r.url()}`);
  });
  return errors;
}
const slotNames = (page) =>
  page.$$eval(".slot.filled", (els) => els.map((e) => e.getAttribute("aria-label").replace(/^Remove /, "")));
const settle = (page) => page.waitForTimeout(400);

async function step(name, fn) {
  process.stdout.write(`- ${name} … `);
  await fn();
  console.log("ok");
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 950 } });
  const page = await ctx.newPage();
  const errors = await watch(page);
  await page.goto(BASE + "/");
  await page.waitForSelector(".item-card");

  await step("pick a hero and buy items", async () => {
    await page.selectOption("#build-panel select", "Haze");
    await settle(page);
    for (const n of ["Headshot Booster", "Extra Health", "Toxic Bullets"]) {
      await page.click(`button[aria-label="Add ${n}"]`);
      await settle(page);
    }
    assert.deepStrictEqual(await slotNames(page), ["Headshot Booster", "Extra Health", "Toxic Bullets"]);
  });

  await step("buying an upgrade consumes its component", async () => {
    await page.click('button[aria-label="Add Headhunter"]');
    await settle(page);
    assert.deepStrictEqual(await slotNames(page), ["Headhunter", "Extra Health", "Toxic Bullets"]);
  });

  await step("undo and redo restore the item list", async () => {
    await page.click("#build-panel button:text-is('Undo')");
    await settle(page);
    assert.deepStrictEqual(await slotNames(page), ["Headshot Booster", "Extra Health", "Toxic Bullets"]);
    await page.keyboard.press("Control+Shift+Z");
    await settle(page);
    assert.deepStrictEqual(await slotNames(page), ["Headhunter", "Extra Health", "Toxic Bullets"]);
    await page.keyboard.press("Control+Z");
    await settle(page);
    assert.deepStrictEqual(await slotNames(page), ["Headshot Booster", "Extra Health", "Toxic Bullets"]);
    await page.keyboard.press("Control+Shift+Z");
    await settle(page);
  });

  await step("removing an item by clicking its slot", async () => {
    await page.click('button[aria-label="Remove Extra Health"]');
    await settle(page);
    assert.deepStrictEqual(await slotNames(page), ["Headhunter", "Toxic Bullets"]);
  });

  await step("ability tiers buy and refund", async () => {
    const tierOf = () => page.evaluate(() => S.build.ability_upgrades[0] || 0);
    await page.click(".ability >> nth=0 >> .tier-btn.buyable >> nth=0");
    await settle(page);
    assert.strictEqual(await tierOf(), 1);
    await page.click(".ability >> nth=0 >> .tier-btn.active");
    await settle(page);
    assert.strictEqual(await tierOf(), 0);
  });

  await step("stat breakdown dialog opens and closes", async () => {
    await page.click("button.stat-row");
    assert.ok(await page.isVisible("dialog[open]"));
    await page.keyboard.press("Escape");
    assert.ok(!(await page.isVisible("dialog[open]")));
  });

  await step("impact sort shows score badges", async () => {
    await page.selectOption(".filters label:nth-of-type(2) select", "★ Gun DPS");
    await page.waitForSelector(".item-card .badge");
    await page.selectOption(".filters label:nth-of-type(2) select", "Cost");
  });

  await step("'/' focuses item search and filters the shop", async () => {
    await page.click("h1");
    await page.keyboard.press("/");
    assert.strictEqual(await page.evaluate(() => document.activeElement.id), "shop-search");
    await page.keyboard.type("magazine");
    await settle(page);
    const names = await page.$$eval(".item-card .nm", (els) => els.map((e) => e.textContent));
    assert.ok(names.length > 0 && names.every((n) => /magazine/i.test(n)), names.join(", "));
    await page.fill("#shop-search", "");
  });

  await step("save, then the build appears under Saved Builds", async () => {
    await page.click("#build-panel button.tiny.primary");
    await page.fill("dialog input", "Smoke test build");
    await page.click("dialog button.primary");
    await page.click("#tabs button:text-is('Saved Builds')");
    await page.waitForSelector("text=Smoke test build");
  });

  await step("share link reproduces the build in a fresh page", async () => {
    const code = await page.evaluate(() => S.view.share_code);
    const items = await page.evaluate(() => S.build.items);
    const other = await ctx.newPage();
    const otherErrors = await watch(other);
    await other.goto(`${BASE}/#b=${code}`);
    await other.waitForSelector(".slot.filled");
    assert.deepStrictEqual(await slotNames(other), items);
    assert.deepStrictEqual(otherErrors, []);
    await other.close();
  });

  await step("Alt+number switches tabs", async () => {
    await page.keyboard.press("Alt+3");
    assert.strictEqual(await page.textContent("#tabs button[aria-selected=true]"), "Simulation");
  });

  await step("every tab renders", async () => {
    for (const t of TABS) {
      await page.click(`#tabs button:text-is("${t}")`);
      await page.waitForTimeout(700);
      assert.ok((await page.textContent("main")).trim().length > 50, `${t} is empty`);
    }
  });

  await step("simulation and Monte Carlo produce results", async () => {
    await page.click("#tabs button:text-is('Simulation')");
    await page.click("text=Run simulation");
    await page.waitForSelector(".banner strong");
    await page.click("text=Monte Carlo gun duel");
    await page.waitForSelector("text=One magazine");
    assert.ok((await page.$$(".chart svg")).length >= 3);
  });

  await step("optimizer result can be loaded into the build", async () => {
    await page.click("#tabs button:text-is('Analysis')");
    await page.click("button:text-is('Optimize')");
    await page.waitForSelector("text=Use this build", { timeout: 60000 });
    await page.click("text=Use this build");
    await page.waitForSelector("#build-panel");
    assert.ok((await slotNames(page)).length >= 2);
  });

  await step("state survives a reload", async () => {
    await settle(page);
    const before = await slotNames(page);
    await page.reload();
    await page.waitForSelector(".slot.filled");
    assert.deepStrictEqual(await slotNames(page), before);
  });

  await step("no horizontal scrolling at phone width", async () => {
    const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const phoneErrors = await watch(phone);
    await phone.goto(BASE + "/");
    await phone.waitForSelector(".item-card");
    const overflowing = [];
    for (const t of TABS) {
      await phone.click(`#tabs button:text-is("${t}")`);
      await phone.waitForTimeout(700);
      const over = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (over > 1) overflowing.push(`${t} (+${over}px)`);
    }
    assert.deepStrictEqual(overflowing, [], "overflow at 390px: " + overflowing.join(", "));
    assert.deepStrictEqual(phoneErrors, []);
    await phone.close();
  });

  assert.deepStrictEqual(errors, [], errors.join("\n"));
  await browser.close();
  console.log("\nAll smoke checks passed.");
})().catch((e) => {
  console.error("\nFAILED:", e.message);
  process.exit(1);
});
