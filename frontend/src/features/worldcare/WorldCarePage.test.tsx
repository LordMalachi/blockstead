import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { WorldCarePage } from "./WorldCarePage";

vi.mock("../servers/scope", () => ({
  useServerScope: () => ({
    profile: { id: "profile-1", name: "Home", distribution: "vanilla", minecraft_version: "1.21.8" },
  }),
}));

test("shows world, protection, cleanup review, and destination resilience controls", async () => {
  const worldCare = {
    worlds: [{ name: "world", size_bytes: 2048 }],
    world_size_bytes: 2048,
    disk: { state: "available", path: "/srv", total_bytes: 10000, free_bytes: 5000, used_bytes: 5000, used_percent: 50 },
    last_verified_backup: null,
    backup_destinations: [{ label: "Blockstead local backup storage", configured_path: "/data/backups", stored_bytes: 1024, disk: { state: "available", path: "/data/backups", total_bytes: 10000, free_bytes: 5000, used_bytes: 5000, used_percent: 50 }, last_check: null }],
    recovery: { entries: [{ label: "Settings snapshots", size_bytes: 128, state: "available" }], total_bytes: 128 },
    cleanup: { available: true, detail: "Build a reviewed cleanup plan before removing anything." },
  };
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const payload = url.endsWith("/cleanup-plan")
      ? { plan_id: "plan-1", created_at: "2026-08-07T00:00:00Z", expires_at: "2026-08-07T00:15:00Z", can_apply: true, blockers: [], protected: [{ label: "Settings snapshots", detail: "Protected" }], targets: [{ path: "backups/profile-1/.interrupted.partial", label: "Interrupted backup fragment", size_bytes: 12, reason: "Stale", recovery_effect: "Not a backup." }] }
      : worldCare;
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(<MemoryRouter><QueryClientProvider client={client}><WorldCarePage /></QueryClientProvider></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Protect the world before you change it" })).toBeVisible();
  expect(screen.getAllByText("2.0 KB").length).toBeGreaterThan(0);
  expect(screen.getByText("Reviewed cleanup only")).toBeVisible();
  expect(screen.getByRole("button", { name: "Test resilience" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Review cleanup" }));
  await waitFor(() => expect(screen.getByText("Interrupted backup fragment")).toBeVisible());
  expect(screen.getByRole("button", { name: "Remove reviewed artifacts" })).toBeVisible();
});
