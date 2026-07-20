import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import type { DiagnosticsReport } from "../../api/client";

const report: DiagnosticsReport = {
  report_version: 1,
  generated_at: "2026-07-19T12:00:00+00:00",
  application: { version: "0.1.0", python: "3.12.4", platform: "Linux-6.8" },
  settings: { bind_host: "127.0.0.1", port: 8765, data_dir: "/var/lib/blockstead", server_root: "/srv/minecraft", secure_cookies: false, session_hours: 12, allowed_origins: ["http://127.0.0.1:8765"], static_dir_present: true },
  host: { cpu_percent: 12, memory: { total_bytes: 8e9, used_bytes: 4e9, percent: 50 }, disk: { total_bytes: 5e10, used_bytes: 4e10, percent: 80 }, uptime_seconds: 3600 },
  java_runtimes: [{ path: "/usr/bin/java", version: "21.0.2", major: 21 }],
  server: { state: "STOPPED", pid: null, exit_code: null, reason: "Not started" },
  profiles: [{ id: "p1", name: "Family world", distribution: "vanilla", minecraft_version: "1.21.1", loader_version: null, is_fixture: false, directory: "/srv/minecraft/family" }],
  schedules: [],
  recent_automation_runs: [],
  recent_backups: [],
  audit_tail: [],
  recent_errors: [{ at: "2026-07-19T11:59:00+00:00", level: "WARNING", logger: "blockstead.api", message: "The managed server did not stop before the timeout" }],
  recent_log: [],
};

test("the panel summarizes the installation and offers the report download", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(
    JSON.stringify(report), { status: 200, headers: { "Content-Type": "application/json" } },
  ))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><DiagnosticsPanel /></QueryClientProvider>);

  expect(await screen.findByText("0.1.0")).toBeVisible();
  expect(screen.getByText("21 (1 found)")).toBeVisible();
  expect(screen.getByText("The managed server did not stop before the timeout")).toBeVisible();
  const download = screen.getByRole("link", { name: "Download report" });
  expect(download).toHaveAttribute("href", "/api/v1/system/diagnostics/report");
  expect(download).toHaveAttribute("download");

  client.clear();
  vi.unstubAllGlobals();
});

test("a quiet installation reports no recent problems", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(
    JSON.stringify({ ...report, recent_errors: [] }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  ))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><DiagnosticsPanel /></QueryClientProvider>);

  expect(await screen.findByText("No warnings or errors have been recorded recently.")).toBeVisible();

  client.clear();
  vi.unstubAllGlobals();
});
