import { expect, test } from "@playwright/test";

test("first admin imports and controls the owned fixture", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to Blockstead" })).toBeVisible();
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.getByRole("button", { name: "Create administrator" }).click();
  await expect(page.getByRole("heading", { name: "Servers", level: 1 })).toBeVisible();

  await page.getByRole("button", { name: /Use an existing server/ }).click();
  await page.getByLabel("Profile name").fill("Vanilla test fixture");
  await page.getByLabel("Server folder").fill("fixtures/servers/vanilla-fixture");
  await page.getByRole("button", { name: "Scan folder" }).click();
  await expect(page.getByRole("heading", { name: "Import plan" })).toBeVisible();
  await expect(page.getByText("Do not modify or launch imported files")).toBeVisible();
  await page.getByRole("button", { name: "Confirm profile record" }).click();

  // Importing opens the new server's own workspace, which names the profile it belongs to.
  await expect(page).toHaveURL(/\/servers\/[^/]+\/overview$/);
  await expect(page.getByRole("heading", { name: "Vanilla test fixture", level: 1 })).toBeVisible();
  const workspace = new URL(page.url()).pathname.replace(/\/overview$/, "");

  await page.getByRole("button", { name: "Start server" }).click();
  await expect(page.getByText("Running", { exact: true })).toBeVisible({ timeout: 5_000 });

  await page.getByRole("link", { name: "Console" }).click();
  await expect(page).toHaveURL(`${workspace}/console`);
  await page.getByLabel("Minecraft console command").fill("say hello from browser test");
  await page.getByRole("button", { name: "Send command" }).click();
  await expect(page.getByRole("log")).toContainText("say hello from browser test");

  await page.getByRole("link", { name: "Players" }).click();
  await expect(page.getByRole("heading", { name: "Players" })).toBeVisible();
  await expect(page.getByText("Steve_Fixture").first()).toBeVisible();
  await page.getByLabel("Player name").fill("Browser_Tester");
  await page.getByRole("button", { name: "Apply" }).click();
  await page.getByRole("link", { name: "Console" }).click();
  await expect(page.getByRole("log")).toContainText("Added Browser_Tester to the whitelist");

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Guided settings" })).toBeVisible();
  await expect(page.getByLabel("Player limit")).toHaveValue("20");
  await expect(page.getByLabel("Difficulty")).toHaveValue("normal");

  await page.getByRole("link", { name: "Backups" }).click();
  await expect(page.getByRole("heading", { name: "Backup Center" })).toBeVisible();
  await page.getByRole("button", { name: "Back up now" }).click();
  await expect(page.getByRole("status")).toContainText("completed successfully", { timeout: 10_000 });
  await expect(page.getByRole("cell", { name: "Protected world." })).toBeVisible();

  await page.getByRole("link", { name: "System" }).click();
  await expect(page.getByRole("heading", { name: "System health" })).toBeVisible();
  await expect(page.getByText("Host CPU")).toBeVisible();

  // Lifecycle stays one interaction away from every server page.
  await page.getByRole("link", { name: "Overview" }).click();
  const pidTile = page.getByText("Process ID").locator("..");
  const pidBefore = (await pidTile.textContent()) ?? "";
  await page.getByRole("button", { name: "Restart" }).click();
  await expect(pidTile).not.toHaveText(pidBefore, { timeout: 10_000 });
  await expect(page.getByText("Running", { exact: true })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Stop safely" }).click();
  await expect(page.getByText("Stopped", { exact: true })).toBeVisible({ timeout: 5_000 });

  // A bookmarked deep link, a refresh, and history all land on the expected view.
  await page.goto(`${workspace}/schedule`);
  await expect(page.getByRole("heading", { name: "Server schedule" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Vanilla test fixture", level: 1 })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(`${workspace}/schedule`);
  await expect(page.getByRole("heading", { name: "Server schedule" })).toBeVisible();
  await page.getByRole("link", { name: "Mods and plugins" }).click();
  await expect(page).toHaveURL(`${workspace}/mods`);
  await page.goBack();
  await expect(page).toHaveURL(`${workspace}/schedule`);
  await page.goForward();
  await expect(page).toHaveURL(`${workspace}/mods`);
});
