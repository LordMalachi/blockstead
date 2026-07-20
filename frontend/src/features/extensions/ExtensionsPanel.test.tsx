import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

function renderPanel(stopped = true, view: ExtensionsView = inventory) {
  const fetch = vi.fn().mockImplementation((url: string) => {
    const target = url;
    const body = target.includes("/catalog/categories") ? { categories: ["optimization", "technology"] }
      : target.includes("/catalog/versions") ? versionList
      : target.includes("/catalog/search") ? searchPage
      : target.includes("/extensions/updates") ? updatesResponse
      : target.includes("/settings/curseforge") ? { configured: false }
      : view;
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ExtensionsPanel profileId="profile-1" stopped={stopped} /></QueryClientProvider>);
  return fetch;
}

test("shows installed extension metadata and inventory warnings", async () => {
  renderPanel();
  expect(await screen.findByText("Lithium")).toBeVisible();
  expect(screen.getByText("lithium.jar")).toBeVisible();
  expect(screen.getByText("This mod belongs on a client.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Disable" })).toBeEnabled();
});

test("locks file changes while the server is active", async () => {
  renderPanel(false);
  expect(await screen.findByText("Lithium")).toBeVisible();
  expect(screen.getByRole("button", { name: "Disable" })).toBeDisabled();
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
  fireEvent.change(await screen.findByLabelText("Search server-compatible projects"), { target: { value: "lithium" } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  expect(await screen.findByText("Performance mod.")).toBeVisible();

  fireEvent.click(await screen.findByRole("button", { name: "optimization" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("categories=optimization"), expect.anything()));

  fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "downloads" } });
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("sort=downloads"), expect.anything()));

  expect(screen.getByText("1–20 of 64")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("offset=20"), expect.anything()));

  fireEvent.click(screen.getByRole("button", { name: "Versions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Install this version" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/extensions/install",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ project_id: "proj-lithium", source: "modrinth", version_id: "ver-2" }) }),
  ));
});

test("checks for updates and applies one through the update endpoint", async () => {
  const fetch = renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Check for updates" }));
  expect(await screen.findByText("1 update available.")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Update to 2.0" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/extensions/update",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ file_name: "lithium.jar" }) }),
  ));
});

test("offers Hangar only for plugin servers and passes the source through", async () => {
  const paperInventory: ExtensionsView = { ...inventory, directory: "plugins", entries: [], disabled_entries: [], warnings: [] };
  const fetch = renderPanel(true, paperInventory);
  const picker = await screen.findByLabelText("Catalog");
  fireEvent.change(picker, { target: { value: "hangar" } });
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/catalog/categories?source=hangar"), expect.anything()));

  fireEvent.change(screen.getByLabelText("Search server-compatible projects"), { target: { value: "essentials" } });
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
