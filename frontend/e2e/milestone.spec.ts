import { expect, test } from "@playwright/test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { crc32 } from "node:zlib";

/** Build a minimal, uncompressed (stored) zip archive without a library dependency. */
function buildStoredZip(entries: { name: string; data: Buffer }[]): Buffer {
  const localParts: Buffer[] = [];
  const centralParts: Buffer[] = [];
  let offset = 0;
  for (const { name, data } of entries) {
    const nameBuf = Buffer.from(name, "utf-8");
    const crc = crc32(data) >>> 0;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(0x21, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28);
    localParts.push(local, nameBuf, data);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(0x21, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt16LE(0, 30);
    central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34);
    central.writeUInt16LE(0, 36);
    central.writeUInt32LE(0, 38);
    central.writeUInt32LE(offset, 42);
    centralParts.push(central, nameBuf);

    offset += local.length + nameBuf.length + data.length;
  }
  const centralStart = offset;
  const centralBuffer = Buffer.concat(centralParts);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralBuffer.length, 12);
  end.writeUInt32LE(centralStart, 16);
  end.writeUInt16LE(0, 20);
  return Buffer.concat([...localParts, centralBuffer, end]);
}

test("first admin imports and controls the owned fixture", async ({ page }) => {
  test.setTimeout(60_000);
  // The fixture is imported in place (not copied), so a previously interrupted
  // run's archive-extract output could otherwise linger and change this run's
  // World-category listing.
  const extractedDatapacks = resolve(
    process.cwd(), "../fixtures/servers/vanilla-fixture/world/datapacks",
  );
  rmSync(extractedDatapacks, { recursive: true, force: true });
  await page.goto("/");
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/manifest.webmanifest");
  await expect(page.getByRole("heading", { name: "Welcome to Blockstead" })).toBeVisible();
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password").fill("correct horse battery staple");
  await page.getByRole("button", { name: "Create administrator" }).click();
  await expect(page.getByRole("heading", { name: "Servers", level: 1 })).toBeVisible();

  await page.getByRole("button", { name: /Use an existing server/ }).click();
  await page.getByLabel("Profile name").fill("Vanilla test fixture");
  await page.getByText("The folder is already inside /srv/minecraft").click();
  await page.getByLabel("Full path").fill("fixtures/servers/vanilla-fixture");
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
  await page.getByText("Advanced raw command").click();
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

  // Session tracking is parsed from the server's own log, so it is only
  // observable once a recognized join/leave line has actually appeared there.
  // Leaving Console and coming back remounts it, so the raw command section
  // collapses again and needs reopening.
  await page.getByText("Advanced raw command").click();
  await page.getByLabel("Minecraft console command").fill("simulate-join Steve_Fixture");
  await page.getByRole("button", { name: "Send command" }).click();
  await expect(page.getByRole("log")).toContainText("Steve_Fixture joined the game");

  await page.getByRole("link", { name: "Players" }).click();
  const steveRow = page.locator(".roster-row", { hasText: "Steve_Fixture" });
  await expect(steveRow.getByText("Likely online")).toBeVisible({ timeout: 10_000 });
  await steveRow.getByRole("button", { name: "Kick" }).click();
  await steveRow.getByRole("button", { name: "Confirm kick" }).click();
  await expect(steveRow.getByText(/Last seen/)).toBeVisible({ timeout: 10_000 });

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Guided settings" })).toBeVisible();
  await expect(page.getByLabel("Player limit")).toHaveValue("20");
  await expect(page.getByLabel("Difficulty")).toHaveValue("normal");

  await page.getByRole("link", { name: "Backups" }).click();
  await expect(page.getByRole("heading", { name: "Backup Center" })).toBeVisible();
  await page.getByRole("button", { name: "Back up now" }).click();
  await expect(page.getByRole("status")).toContainText(/completed.*verified/i, { timeout: 10_000 });
  await expect(page.getByText("Protected world.")).toBeVisible();

  await page.getByRole("link", { name: "Files" }).click();
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();
  await expect(page.getByRole("button", { name: /server\.properties/ })).toBeVisible();
  await page.getByLabel("Choose files").setInputFiles({
    name: "note.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("hello from the browser test\n"),
  });
  await expect(page.getByText("Uploaded 1 file.")).toBeVisible();
  const noteRow = page.locator(".file-row", { hasText: "note.txt" });
  await expect(noteRow).toBeVisible();

  await noteRow.getByRole("button", { name: /note\.txt/ }).click();
  await page.getByLabel("Content of note.txt").fill("hello from the browser test, edited\n");
  await page.getByRole("button", { name: "Check changes" }).click();
  const saveFile = page.getByRole("button", { name: "Save file" });
  await expect(saveFile).toBeEnabled();
  await saveFile.click();
  await expect(page.getByText(/Recovery snapshot/)).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();

  await noteRow.getByRole("button", { name: "Rename" }).click();
  await page.getByLabel("New name for note.txt").fill("renamed-note.txt");
  await noteRow.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".file-row", { hasText: "renamed-note.txt" })).toBeVisible();

  const renamedRow = page.locator(".file-row", { hasText: "renamed-note.txt" });
  await renamedRow.getByRole("button", { name: "Delete" }).click();
  await renamedRow.getByRole("button", { name: "Confirm delete" }).click();
  await expect(page.getByText(/Recovery snapshot/)).toBeVisible();
  await expect(page.locator(".file-row", { hasText: "renamed-note.txt" })).toHaveCount(0);

  await page.getByRole("link", { name: "System" }).click();
  await expect(page.getByRole("heading", { name: "System health" })).toBeVisible();
  await expect(page.getByText("Host CPU")).toBeVisible();

  await page.getByRole("link", { name: "Help" }).click();
  await expect(page.getByRole("heading", { name: "How can we help?" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search help" }).fill("backup");
  await expect(page.getByRole("heading", { name: "Protect, save, and restore a world" })).toBeVisible();
  await page.getByRole("button", { name: "Start guided tour" }).click();
  await expect(page.getByRole("dialog", { name: "A quick tour of Blockstead" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: "Servers is your home base" })).toBeVisible();
  await page.getByRole("button", { name: "Exit tour" }).click();

  // Lifecycle stays one interaction away from every server page.
  await page.getByRole("link", { name: "Overview" }).click();
  const pidTile = page.getByText("Process ID").locator("..");
  const pidBefore = (await pidTile.textContent()) ?? "";
  await page.getByRole("button", { name: "Restart" }).click();
  await expect(pidTile).not.toHaveText(pidBefore, { timeout: 10_000 });
  await expect(page.getByText("Running", { exact: true })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Stop safely" }).click();
  await expect(page.getByText("Stopped", { exact: true })).toBeVisible({ timeout: 5_000 });

  // World archive extraction requires a stopped server; validated separately from the
  // config-category upload/edit/rename/delete flow exercised above.
  await page.getByRole("link", { name: "Files" }).click();
  await page.getByRole("button", { name: "World", exact: true }).click();
  const zip = buildStoredZip([
    { name: "datapacks/hello.txt", data: Buffer.from("e2e archive test\n") },
  ]);
  await page.getByRole("button", { name: "world", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Extract a .zip archive here" })).toBeVisible();
  await page.getByLabel("Choose a .zip file").setInputFiles({
    name: "pack.zip",
    mimeType: "application/zip",
    buffer: zip,
  });
  await expect(page.getByText(/^Extracted 1 item\./)).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".file-row", { hasText: "datapacks" })).toBeVisible();
  // The fixture is imported in place; leave it as this test found it.
  rmSync(extractedDatapacks, { recursive: true, force: true });

  // A bookmarked deep link, a refresh, and history all land on the expected view.
  await page.goto(`${workspace}/schedule`);
  await expect(page.getByRole("heading", { name: "Server schedule" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Vanilla test fixture", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Weekend only" }).click();
  await page.getByRole("button", { name: "Save plan" }).click();
  await expect(page.getByRole("status")).toContainText("Automation plan saved");
  await expect(page.getByRole("heading", { name: "What Blockstead will do" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Next three executions" })).toBeVisible();
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

test("a server folder from anywhere on the computer imports through the browser", async ({ page }) => {
  // A previous run may have left the copied folder behind in the fixtures root.
  rmSync(resolve(process.cwd(), "../fixtures/servers/e2e-upload-world"), { recursive: true, force: true });
  const staging = mkdtempSync(join(tmpdir(), "blockstead-e2e-"));
  const world = join(staging, "e2e-upload-world");
  mkdirSync(join(world, "world"), { recursive: true });
  writeFileSync(join(world, "server.properties"), "motd=Uploaded\n");
  writeFileSync(join(world, "server.jar"), "jar");
  writeFileSync(join(world, "world", "level.dat"), "level");

  try {
    await page.goto("/");
    // The milestone test above already created the administrator; sign back in.
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    await page.getByLabel("Username").fill("owner");
    await page.getByLabel("Password").fill("correct horse battery staple");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Servers", level: 1 })).toBeVisible();

    const importCard = page.locator("#import-server");
    await importCard.getByLabel("Profile name").fill("E2E Upload World");
    await importCard.getByLabel("Server folder").setInputFiles(world);
    await expect(importCard.getByText(/Ready to copy/)).toBeVisible();
    await importCard.getByRole("button", { name: "Copy folder in" }).click();

    // The copied folder becomes a normal profile that opens its own workspace.
    await expect(page).toHaveURL(/\/servers\/[^/]+\/overview$/, { timeout: 10_000 });
    await expect(page.getByRole("heading", { name: "E2E Upload World", level: 1 })).toBeVisible();
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
});
