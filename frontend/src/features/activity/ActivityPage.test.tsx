import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { ActivityPage } from "./ActivityPage";

test("shows activity context, recovery, and focused report actions", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = url.endsWith("/profiles") ? [{ id: "p1", name: "Family world", server_directory: "/srv/family", distribution: "paper", minecraft_version: "1.21.1", loader_version: null, is_fixture: false }]
      : url.endsWith("/notifications") ? { alerts: [{ id: "low-disk-space", kind: "low_disk_space", title: "Disk space is running low", detail: "The data disk is 92% full.", severity: "warning", created_at: "2026-07-21T12:01:00Z", recovery_to: "/system" }], unread_count: 1 }
        : url.endsWith("/notification-preferences") ? { server_crashes: true, failed_backups: true, low_disk_space: true, completed_updates: true, show_player_avatars: false, last_seen_at: null }
          : { events: [{ id: "event-1", category: "manual_backup", group: "backup", title: "Manual backup", result: "failed", severity: "danger", detail: "Backup failed because the disk is full", actor: "owner", profile: { id: "p1", name: "Family world" }, created_at: "2026-07-21T12:00:00Z", recovery_to: "/servers/p1/backups", report_url: "/api/v1/activity/event-1/report" }], total: 1, limit: 50, offset: 0 };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(<MemoryRouter><QueryClientProvider client={client}><ActivityPage /></QueryClientProvider></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Activity", level: 1 })).toBeVisible();
  expect(await screen.findByText("Backup failed because the disk is full")).toBeVisible();
  expect(screen.getByText("owner · Family world · backup")).toBeVisible();
  expect(screen.getAllByRole("link", { name: "Open recovery" }).some(link => link.getAttribute("href") === "/servers/p1/backups")).toBe(true);
  expect(screen.getByRole("link", { name: "Download support report" })).toHaveAttribute("href", "/api/v1/activity/event-1/report");
  expect(screen.getByRole("checkbox", { name: /Server crashes/ })).toBeChecked();
  expect(screen.getByRole("button", { name: /What does Mark seen do?/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /How do outcomes and support reports work?/ })).toBeVisible();

  client.clear();
  vi.unstubAllGlobals();
});
