import { expect, test } from "@playwright/test";

test("first admin imports and controls the owned fixture", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to Blockstead" })).toBeVisible();
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.getByRole("button", { name: "Create administrator" }).click();
  await expect(page.getByRole("heading", { name: "Your server, at a glance" })).toBeVisible();

  await page.getByRole("button", { name: "Scan folder" }).click();
  await expect(page.getByRole("heading", { name: "Import plan" })).toBeVisible();
  await expect(page.getByText("Do not modify or launch imported files")).toBeVisible();
  await page.getByRole("button", { name: "Confirm profile record" }).click();
  await expect(page.getByText("Profiles").locator("..").getByText("1")).toBeVisible();

  await page.getByRole("button", { name: "Start server" }).click();
  await expect(page.getByText("Running", { exact: true })).toBeVisible({ timeout: 5_000 });
  await page.getByLabel("Minecraft console command").fill("say hello from browser test");
  await page.getByRole("button", { name: "Send command" }).click();
  await expect(page.getByRole("log")).toContainText("say hello from browser test");

  await expect(page.getByRole("heading", { name: "Players" })).toBeVisible();
  await expect(page.getByText("Steve_Fixture").first()).toBeVisible();
  await page.getByLabel("Player name").fill("Browser_Tester");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("log")).toContainText("Added Browser_Tester to the whitelist");

  await expect(page.getByRole("heading", { name: "Server settings" })).toBeVisible();
  await expect(page.getByRole("row", { name: /Player limit/ })).toContainText("20");
  await expect(page.getByRole("heading", { name: "System health" })).toBeVisible();
  await expect(page.getByText("Host CPU")).toBeVisible();

  const pidTile = page.getByText("Process ID").locator("..");
  const pidBefore = (await pidTile.textContent()) ?? "";
  await page.getByRole("button", { name: "Restart" }).click();
  await expect(pidTile).not.toHaveText(pidBefore, { timeout: 10_000 });
  await expect(page.getByText("Running", { exact: true })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Stop safely" }).click();
  await expect(page.getByText("Stopped", { exact: true })).toBeVisible({ timeout: 5_000 });
});
