import { expect, test } from "@playwright/test";

// Documentation screenshots: run with `npm run screenshots`.
// Writes PNG files into docs/screenshots at the repository root.
const out = (name: string) => `../docs/screenshots/${name}.png`;

test("captures documentation screenshots @docs", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 850 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to Blockstead" })).toBeVisible();
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.screenshot({ path: out("01-first-run") });
  await page.getByRole("button", { name: "Create administrator" }).click();

  await expect(page.getByRole("heading", { name: "Your server, at a glance" })).toBeVisible();
  await page.getByRole("button", { name: "Scan folder" }).click();
  await expect(page.getByRole("heading", { name: "Import plan" })).toBeVisible();
  await page.screenshot({ path: out("02-import-plan"), fullPage: true });
  await page.getByRole("button", { name: "Confirm profile record" }).click();

  await page.getByRole("button", { name: "Start server" }).click();
  await expect(page.getByText("Running", { exact: true })).toBeVisible({ timeout: 5_000 });
  await page.getByRole("button", { name: "Who is online?" }).click();
  await expect(page.getByRole("log")).toContainText("players online");
  await page.getByRole("link", { name: "Overview" }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: out("03-overview-running") });

  await page.getByLabel("Player name").fill("New_Neighbor");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("log")).toContainText("Added New_Neighbor to the whitelist");
  // Un-stick the topbar so it cannot overlap element captures further down the page.
  await page.addStyleTag({ content: ".topbar { position: static !important; }" });
  await page.locator("#console").screenshot({ path: out("04-console") });
  await page.locator("#players").screenshot({ path: out("05-players") });
  await page.locator("#settings").screenshot({ path: out("06-settings") });
  await expect(page.getByText("Host CPU")).toBeVisible();
  // Let the metrics poller take a second CPU sample so the tile shows a real value.
  await page.waitForTimeout(2_500);
  await page.locator("#system").screenshot({ path: out("07-system") });

  await page.getByRole("button", { name: "Stop safely" }).click();
  await expect(page.getByText("Stopped", { exact: true })).toBeVisible({ timeout: 5_000 });
});
