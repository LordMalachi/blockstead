import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { ExtensionsPanel } from "./ExtensionsPanel";
import type { ExtensionsView } from "../../api/client";

const inventory: ExtensionsView = {
  directory: "mods",
  present: true,
  entries: [{ file_name: "lithium.jar", size_bytes: 2048, sha256: "a", kind: "fabric-mod", loaders: ["fabric"], identifier: "lithium", display_name: "Lithium", version: "1.0", minecraft_constraint: "1.21.1", environment: "*", dependencies: [], readable: true }],
  disabled_entries: [],
  warnings: [{ code: "client-only", message: "This mod belongs on a client.", files: ["shader.jar"] }],
  truncated: false,
};

const searchPage = {
  minecraft_version: "1.21.1",
  projects: [{ project_id: "proj-lithium", slug: "lithium", title: "Lithium", description: "Performance mod.", downloads: 9000, author: "caffeine" }],
  total: 64,
  offset: 0,
  limit: 20,
};

const versionList = {
  versions: [{ version_id: "ver-2", version_number: "2.0.0", version_type: "release", date_published: "2026-05-01T00:00:00Z", game_versions: ["1.21.1"], loaders: ["fabric"] }],
};

const updatesResponse = {
  updates: [{ file_name: "lithium.jar", installed_version: "1.0", new_version_number: "2.0", new_file_name: "lithium-2.0.jar", project_id: "proj-lithium", version_id: "ver-2" }],
  up_to_date: 0,
  unknown: [],
  checked: 1,
};
const updateReview = {
  review: {
    review_id: "1234567890abcdef",
    file_name: "lithium.jar",
    installed_version: "1.0",
    new_file_name: "lithium-2.0.jar",
    new_version_number: "2.0",
    project_id: "proj-lithium",
    version_id: "ver-2",
    minecraft_version: "1.21.1",
    distribution: "fabric",
    required_java_major: 21,
    files: [
      { file_name: "lithium-2.0.jar", version_number: "2.0", role: "replacement", action: "replace", required_by: null },
      { file_name: "fabric-api.jar", version_number: "1.0", role: "dependency", action: "install", required_by: "lithium-2.0.jar" },
    ],
    dependencies: ["fabric-api.jar"],
    restart_required: true,
    rollback_detail: "Blockstead keeps the exact replaced jar in a private recovery bundle.",
  },
  maintenance_plan: {
    catalog_version: "2026.07.1",
    plan_id: "fedcba0987654321",
    profile_id: "profile-1",
    change: { id: "extension_update", title: "Update installed mods or plugins", summary: "", workspace: "mods", requires_stopped_server: true, version_changing: true, destructive: false, restart_expectation: "required", checks: [] },
    readiness: "ready",
    headline: "Safe",
    detail: "Safe",
    findings: [],
    steps: [],
    protection: { verified: true, detail: "Fresh backup", backup_id: "backup-1", created_at: "2026-07-26T12:00:00Z", age_hours: 1 },
    restart: "required",
    restart_detail: "Restart required",
    blockers: [],
    reviewed_at: "2026-07-26T13:00:00Z",
  },
};
const appliedUpdate = {
  file_name: "lithium-2.0.jar",
  replaced: "lithium.jar",
  version_number: "2.0",
  dependencies_installed: ["fabric-api.jar"],
  recovery_id: "abcdef1234567890abcdef12",
  rollback_detail: updateReview.review.rollback_detail,
  restart_required: true,
};

function renderPanel(stopped = true, view: ExtensionsView = inventory) {
  const fetch = vi.fn().mockImplementation((url: string) => {
    const target = url;
    const body = target.includes("/catalog/categories") ? { categories: ["optimization", "technology"] }
      : target.includes("/catalog/versions") ? versionList
      : target.includes("/catalog/search") ? searchPage
      : target.includes("/extensions/update-review") ? updateReview
      : target.endsWith("/extensions/update") ? appliedUpdate
      : target.includes("/extensions/updates") ? updatesResponse
      : target.includes("/settings/curseforge") ? { configured: false }
      : view;
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><ExtensionsPanel profileId="profile-1" stopped={stopped} /></MemoryRouter></QueryClientProvider>);
  return fetch;
}

test("shows installed extension metadata and inventory warnings", async () => {
  renderPanel();
  expect(await screen.findByText("Lithium")).toBeVisible();
  expect(screen.getByText("lithium.jar")).toBeVisible();
  expect(screen.getByText("This mod belongs on a client.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Disable Lithium" })).toBeEnabled();
});

test("locks file changes while the server is active", async () => {
  renderPanel(false);
  expect(await screen.findByText("Lithium")).toBeVisible();
  expect(screen.getByRole("button", { name: "Disable Lithium" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  expect(screen.getByText("Stop the server before changing extension files.")).toBeVisible();
});

test("offers the vanilla switch and disables everything through toggle-all", async () => {
  const fetch = renderPanel();
  expect(await screen.findByText("Vanilla switch")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Enable all" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Disable all" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/extensions/toggle-all",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ enabled: false }),
    }),
  ));
});

test("searches with filters, pages results, and installs a chosen version", async () => {
  const fetch = renderPanel();
  fireEvent.change(await screen.findByLabelText("Search projects listed for this server"), { target: { value: "lithium" } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByText("Performance mod.")).toBeVisible();

  fireEvent.click(await screen.findByRole("button", { name: "optimization" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("categories=optimization"), expect.anything()));

  fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "downloads" } });
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("sort=downloads"), expect.anything()));

  expect(screen.getByText("1–20 of 64")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("offset=20"), expect.anything()));

  fireEvent.click(screen.getByRole("button", { name: "Show versions for Lithium" }));
  fireEvent.click(await screen.findByRole("button", { name: "Install version 2.0.0" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/extensions/install",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ project_id: "proj-lithium", source: "modrinth", version_id: "ver-2" }) }),
  ));
});

test("reviews exact update impact before applying it", async () => {
  const fetch = renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Check for updates" }));
  expect(await screen.findByText("1 update available.")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Review update for Lithium to 2.0" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/extensions/update-review",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ file_name: "lithium.jar" }) }),
  ));
  expect(await screen.findByText(/The server still requires Java 21/)).toBeVisible();
  expect(screen.getByText("fabric-api.jar")).toBeVisible();
  expect(screen.getByText(/exact replaced jar/)).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Apply reviewed update" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/extensions/update",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        file_name: "lithium.jar",
        review_id: "1234567890abcdef",
        maintenance_plan_id: "fedcba0987654321",
      }),
    }),
  ));
  expect(await screen.findByRole("button", { name: "Undo this update" })).toBeVisible();
});

test("offers Hangar only for plugin servers and passes the source through", async () => {
  const paperInventory: ExtensionsView = { ...inventory, directory: "plugins", entries: [], disabled_entries: [], warnings: [] };
  const fetch = renderPanel(true, paperInventory);
  const picker = await screen.findByLabelText("Catalog");
  fireEvent.change(picker, { target: { value: "hangar" } });
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/catalog/categories?source=hangar"), expect.anything()));

  fireEvent.change(screen.getByLabelText("Search projects listed for this server"), { target: { value: "essentials" } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("source=hangar&query=essentials"), expect.anything()));
});

test("mod servers see Modrinth and CurseForge but never Hangar", async () => {
  renderPanel();
  expect(await screen.findByText("Lithium")).toBeVisible();
  expect(screen.getByRole("option", { name: "Modrinth" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "CurseForge" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "Hangar (PaperMC)" })).not.toBeInTheDocument();
});

test("curseforge asks for an API key once and saves it", async () => {
  const fetch = renderPanel();
  fireEvent.change(await screen.findByLabelText("Catalog"), { target: { value: "curseforge" } });
  const keyInput = await screen.findByLabelText("CurseForge API key");
  fireEvent.change(keyInput, { target: { value: "my-secret-key" } });
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/settings/curseforge",
    expect.objectContaining({ method: "PUT", body: JSON.stringify({ api_key: "my-secret-key" }) }),
  ));
});

test("installs the curated squaremap project through the verified extension endpoint", async () => {
  const fetch = renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Install shared map" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/extensions/install",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ project_id: "squaremap" }),
    }),
  ));
});

test("keeps discovery open while a running server protects file changes", async () => {
  renderPanel(false);
  const search = await screen.findByLabelText("Search projects listed for this server");
  fireEvent.change(search, { target: { value: "lithium" } });

  expect(screen.getByRole("button", { name: "Search" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Search" }));

  expect(await screen.findByText("Performance mod.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Install Lithium" })).toBeDisabled();
});

test("opens an in-page guide and exposes contextual help", async () => {
  renderPanel();
  const guide = await screen.findByRole("button", { name: "Open extension guide" });
  fireEvent.click(guide);

  expect(screen.getByRole("heading", { name: "Change mods and plugins safely" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Help: How project filtering works" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Help: When to upload a jar manually" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Close guide" }));
  await waitFor(() => expect(guide).toHaveFocus());
});

test("moves focus through inline removal confirmation", async () => {
  renderPanel();
  const remove = await screen.findByRole("button", { name: "Remove Lithium" });
  remove.focus();
  fireEvent.click(remove);

  expect(screen.getByRole("button", { name: "Permanently remove Lithium" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Cancel removing Lithium" }));

  expect(screen.getByRole("button", { name: "Remove Lithium" })).toHaveFocus();
});
