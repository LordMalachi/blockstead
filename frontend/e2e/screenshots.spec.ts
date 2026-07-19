import { expect, test } from "@playwright/test";

// Documentation screenshots: run with `npm run screenshots`.
// Writes PNG files into docs/screenshots at the repository root.
const out = (name: string) => `../docs/screenshots/${name}.png`;

test("captures documentation screenshots @docs", async ({ page }) => {
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
  await page.getByLabel("Server folder").fill("fixtures/servers/vanilla-fixture");
  await page.getByRole("button", { name: "Scan folder" }).click();
  await expect(page.getByRole("heading", { name: "Import plan" })).toBeVisible();
  await page.screenshot({ path: out("02-import-plan"), fullPage: true });
  await page.getByRole("button", { name: "Confirm profile record" }).click();
  await expect(page).toHaveURL(/\/servers\/[^/]+\/overview$/);

  await page.getByRole("button", { name: "Start server" }).click();
  await expect(page.getByText("Running", { exact: true })).toBeVisible({ timeout: 5_000 });
  await page.getByRole("link", { name: "Console" }).click();
  await page.getByRole("button", { name: "Who is online?" }).click();
  await expect(page.getByRole("log")).toContainText("players online");

  await page.getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { name: "Server readiness" })).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: out("03-overview-running") });

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

  await page.getByRole("link", { name: "System" }).click();
  await expect(page.getByRole("heading", { name: "System health" })).toBeVisible();
  await expect(page.getByText("Host CPU")).toBeVisible();
  // Let the metrics poller take a second CPU sample so the tile shows a real value.
  await page.waitForTimeout(2_500);
  await page.screenshot({ path: out("07-system") });

  await page.getByRole("link", { name: "Servers" }).click();
  await expect(page.getByRole("heading", { name: "Servers", level: 1 })).toBeVisible();
  await page.screenshot({ path: out("08-servers") });

  await page.getByRole("button", { name: "Stop safely" }).click();
  await expect(page.getByText("Stopped", { exact: true })).toBeVisible({ timeout: 5_000 });
});
