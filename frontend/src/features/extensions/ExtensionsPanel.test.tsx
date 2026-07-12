import { render, screen } from "@testing-library/react";
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

function renderPanel(stopped = true) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(inventory), { status: 200, headers: { "Content-Type": "application/json" } })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ExtensionsPanel profileId="profile-1" stopped={stopped} /></QueryClientProvider>);
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
