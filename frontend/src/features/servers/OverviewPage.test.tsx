import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type { ProfileOverview } from "../../api/client";
import { OverviewPage } from "./OverviewPage";

vi.mock("./scope", () => ({
  useServerScope: () => ({
    profile: { id: "profile-1", name: "Home", distribution: "paper", minecraft_version: "1.21.8" },
    state: "RUNNING",
    running: true,
    pid: 4321,
    exitCode: null,
  }),
}));

vi.mock("../extensions/PrerequisitesPanel", () => ({
  PrerequisitesPanel: () => <section aria-label="Server readiness" />,
}));

const overview: ProfileOverview = {
  state: { value: "RUNNING", reason: "Server reported ready", uptime_seconds: 3725 },
  join: { host: "192.168.1.24", port: 25570, address: "192.168.1.24:25570", bind_address: null, candidate_hosts: ["192.168.1.24"], local_only: false },
  players: { online: 2, max: 20, sample: ["Alex", "Steve"], available: true },
  metrics: {
    current: { at: "2026-07-19T15:00:00Z", cpu_percent: 18, memory_percent: 42, disk_percent: 35, process_memory_bytes: 800_000_000, world_size_bytes: 2_000_000_000, memory_used_bytes: 8_000_000_000, memory_total_bytes: 16_000_000_000, disk_used_bytes: 35_000_000_000, disk_total_bytes: 100_000_000_000 },
    history: [
      { at: "2026-07-19T14:59:00Z", cpu_percent: 10, memory_percent: 40, disk_percent: 35, process_memory_bytes: 790_000_000, world_size_bytes: 1_990_000_000 },
      { at: "2026-07-19T15:00:00Z", cpu_percent: 18, memory_percent: 42, disk_percent: 35, process_memory_bytes: 800_000_000, world_size_bytes: 2_000_000_000 },
    ],
  },
  last_backup: null,
  next_operation: { label: "Back up and stop", at: "2026-07-20T03:00:00Z" },
  warnings: [{ code: "backup-missing", title: "This world has not been backed up", detail: "Create a verified backup.", to: "/servers/profile-1/backups", severity: "warning" }],
  activity: [{ id: "event-1", category: "server_start", result: "accepted", detail: "Started Paper profile Home", created_at: "2026-07-19T14:00:00Z", to: "/servers/profile-1/console" }],
  capabilities: { tps: false, mspt: false, distribution_label: "Paper" },
};

test("shows owner health, join address, trends, warnings, and diagnostics", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify(overview), { status: 200, headers: { "Content-Type": "application/json" } }))));
  const writeText = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(<MemoryRouter><QueryClientProvider client={client}><OverviewPage /></QueryClientProvider></MemoryRouter>);

  expect(await screen.findByText("2 / 20")).toBeVisible();
  expect(screen.getByText("192.168.1.24")).toBeVisible();
  expect(screen.getByText("Port").parentElement).toHaveTextContent("25570");
  expect(screen.getByRole("img", { name: "Host CPU recent history" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Resolve" })).toHaveAttribute("href", "/servers/profile-1/backups");
  expect(screen.getByText("Process ID")).toBeInTheDocument();
  expect(screen.getByText("4321")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Copy address" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("192.168.1.24:25570"));
  expect(screen.getByRole("button", { name: "Copied" })).toBeVisible();
});
