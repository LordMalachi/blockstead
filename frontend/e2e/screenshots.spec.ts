import { expect, test } from "@playwright/test";

// Documentation screenshots: run with `npm run screenshots`.
// Writes PNG files into docs/screenshots at the repository root.
const out = (name: string) => `../docs/screenshots/${name}.png`;

test("captures documentation screenshots @docs", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1360, height: 850 });
  // The stylesheet drops transitions under reduced motion, which keeps a capture from
  // catching a nav item mid-crossfade.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to Blockstead" })).toBeVisible();
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.screenshot({ path: out("01-first-run") });
  await page.getByRole("button", { name: "Create administrator" }).click();

  await expect(page.getByRole("heading", { name: "Servers", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: /Use an existing server/ }).click();
  await page.getByLabel("Profile name").fill("Vanilla test fixture");
  await page.getByText("The folder is already inside /srv/minecraft").click();
  await page.getByLabel("Full path").fill("fixtures/servers/vanilla-fixture");
  await page.getByRole("button", { name: "Scan folder" }).click();
  await expect(page.getByRole("heading", { name: "Import plan" })).toBeVisible();
  await page.screenshot({ path: out("02-import-plan"), fullPage: true });
  await page.getByRole("button", { name: "Confirm profile record" }).click();
  await expect(page).toHaveURL(/\/servers\/[^/]+\/overview$/);

  await page.getByRole("button", { name: "Start server" }).click();
  await expect(page.getByText("Running", { exact: true })).toBeVisible({ timeout: 5_000 });

  await page.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { name: "Server readiness" })).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: out("03-overview-running") });
  await page.locator(".hero-actions").screenshot({ path: out("help-tour-server-controls") });
  await page.locator(".hero-actions").screenshot({ path: "public/help/server-controls.png" });

  await page.getByRole("link", { name: "Console" }).click();
  await expect(page.getByRole("heading", { name: "Live server log" })).toBeVisible();
  await page.screenshot({ path: out("04-console") });

  await page.getByRole("link", { name: "Players" }).click();
  await expect(page.getByRole("heading", { name: "Players" })).toBeVisible();
  await page.getByLabel("Player name").fill("New_Neighbor");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("status")).toContainText("New_Neighbor");
  await page.screenshot({ path: out("05-players") });

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Guided settings" })).toBeVisible();
  await expect(page.getByLabel("Player limit")).toBeVisible();
  await page.screenshot({ path: out("06-settings") });

  await page.getByRole("link", { name: "Backups" }).click();
  await expect(page.getByRole("heading", { name: "Backup Center" })).toBeVisible();
  await page.getByRole("button", { name: "Back up now" }).click();
  await expect(page.getByRole("status")).toContainText(/completed and verified/i, { timeout: 10_000 });
  await expect(page.getByText("Protected world.")).toBeVisible();
  await page.setViewportSize({ width: 1360, height: 1080 });
  await page.screenshot({ path: out("11-backups") });
  await page.setViewportSize({ width: 1360, height: 850 });

  await page.getByRole("link", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Stop safely" }).click();
  await expect(page.getByText("Stopped", { exact: true })).toBeVisible({ timeout: 5_000 });

  // The checked-in server fixture is deliberately vanilla. Supply a representative,
  // local-only loadout here so the documentation can show the extension workspace
  // rather than a network-dependent catalog result.
  await page.route(/\/api\/v1\/profiles\/[^/]+\/extensions$/, route => route.fulfill({ json: {
    directory: "mods",
    present: true,
    entries: [
      { file_name: "lithium-fabric-mc1.21.4-0.14.7.jar", size_bytes: 735_000, sha256: "a".repeat(64), kind: "fabric-mod", loaders: ["fabric"], identifier: "lithium", display_name: "Lithium", version: "0.14.7", minecraft_constraint: "1.21.4", environment: "server", dependencies: [], readable: true },
      { file_name: "voicechat-fabric-1.21.4-2.5.28.jar", size_bytes: 2_100_000, sha256: "b".repeat(64), kind: "fabric-mod", loaders: ["fabric"], identifier: "voicechat", display_name: "Simple Voice Chat", version: "2.5.28", minecraft_constraint: "1.21.4", environment: "server", dependencies: [], readable: true },
    ],
    disabled_entries: [
      { file_name: "squaremap-1.3.3.jar.disabled", size_bytes: 1_800_000, sha256: "c".repeat(64), kind: "fabric-mod", loaders: ["fabric"], identifier: "squaremap", display_name: "squaremap", version: "1.3.3", minecraft_constraint: "1.21.4", environment: "server", dependencies: [], readable: true },
    ],
    warnings: [],
    truncated: false,
  } }));
  await page.route(/\/api\/v1\/profiles\/[^/]+\/shared-map$/, route => route.fulfill({ json: {
    config_present: true, config_path: "config/squaremap/config.yml", internal_webserver_enabled: true, bind: "127.0.0.1", port: 8080, problem: null,
  } }));
  await page.route(/\/api\/v1\/profiles\/[^/]+\/catalog\/categories\?source=modrinth$/, route => route.fulfill({ json: {
    categories: ["optimization", "utility", "server"],
  } }));
  await page.route(/\/api\/v1\/profiles\/[^/]+\/configs$/, route => route.fulfill({ json: {
    distribution: "fabric", directory: "config", files: [],
  } }));
  await page.getByRole("link", { name: "Mods and plugins" }).click();
  await expect(page.getByRole("heading", { name: "Extension Workshop" })).toBeVisible();
  await expect(page.getByText("Simple Voice Chat")).toBeVisible();
  await page.setViewportSize({ width: 1360, height: 1280 });
  await page.screenshot({ path: out("10-mods-plugins") });
  await page.setViewportSize({ width: 1360, height: 850 });

  await page.getByRole("link", { name: "Schedule" }).click();
  await expect(page.getByRole("heading", { name: "What Blockstead will do" })).toBeVisible();
  await page.getByRole("button", { name: "Every night" }).click();
  await page.getByRole("button", { name: "Save plan" }).click();
  await expect(page.getByRole("status")).toContainText("Automation plan saved");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: out("09-automation"), fullPage: true });

  await page.getByRole("link", { name: "System" }).click();
  await expect(page.getByRole("heading", { name: "System health" })).toBeVisible();
  await expect(page.getByText("Host CPU")).toBeVisible();
  // Let the metrics poller take a second CPU sample so the tile shows a real value.
  await page.waitForTimeout(2_500);
  await page.screenshot({ path: out("07-system") });
  await page.getByRole("button", { name: "Help: What these measurements include" }).focus();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toBeVisible();
  const tooltipBox = await tooltip.boundingBox();
  expect(tooltipBox).not.toBeNull();
  expect(tooltipBox.x).toBeGreaterThanOrEqual(8);
  expect(tooltipBox.y).toBeGreaterThanOrEqual(8);
  expect(tooltipBox.x + tooltipBox.width).toBeLessThanOrEqual(1352);
  expect(tooltipBox.y + tooltipBox.height).toBeLessThanOrEqual(842);
  await page.screenshot({ path: out("15-contextual-help") });
  await page.keyboard.press("Escape");
  await expect(tooltip).toBeHidden();

  await page.getByRole("link", { name: "Help" }).click();
  await expect(page.getByRole("heading", { name: "How can we help?" })).toBeVisible();
  await page.screenshot({ path: out("12-help") });
  await page.getByRole("button", { name: "Start guided tour" }).click();
  await expect(page.getByRole("dialog", { name: "A quick tour of Blockstead" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Overview showing a running server/ })).toBeVisible();
  await page.screenshot({ path: out("13-guided-tour") });
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: "Servers is your home base" })).toBeVisible();
  await page.screenshot({ path: out("14-guided-tour-spotlight") });
  await page.getByRole("button", { name: "Exit tour" }).click();

  await page.getByRole("link", { name: "Servers" }).click();
  await expect(page.getByRole("heading", { name: "Servers", level: 1 })).toBeVisible();
  await page.screenshot({ path: out("08-servers") });
});
