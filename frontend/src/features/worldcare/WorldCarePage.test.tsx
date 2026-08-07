import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { WorldCarePage } from "./WorldCarePage";

vi.mock("../servers/scope", () => ({
  useServerScope: () => ({
    profile: { id: "profile-1", name: "Home", distribution: "vanilla", minecraft_version: "1.21.8" },
  }),
}));

test("shows world, protection, and recovery evidence without cleanup controls", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    worlds: [{ name: "world", size_bytes: 2048 }],
    world_size_bytes: 2048,
    disk: { state: "available", path: "/srv", total_bytes: 10000, free_bytes: 5000, used_bytes: 5000, used_percent: 50 },
    last_verified_backup: null,
    backup_destinations: [{ label: "Blockstead local backup storage", configured_path: "/data/backups", stored_bytes: 1024, disk: { state: "available", path: "/data/backups", total_bytes: 10000, free_bytes: 5000, used_bytes: 5000, used_percent: 50 } }],
    recovery: { entries: [{ label: "Settings snapshots", size_bytes: 128, state: "available" }], total_bytes: 128 },
    cleanup: { available: false, detail: "Cleanup recommendations are not enabled yet." },
  }), { status: 200, headers: { "Content-Type": "application/json" } }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(<MemoryRouter><QueryClientProvider client={client}><WorldCarePage /></QueryClientProvider></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Protect the world before you change it" })).toBeVisible();
  expect(screen.getAllByText("2.0 KB").length).toBeGreaterThan(0);
  expect(screen.getByText("Cleanup is not enabled")).toBeVisible();
  expect(screen.queryByRole("button", { name: /clean/i })).not.toBeInTheDocument();
});
