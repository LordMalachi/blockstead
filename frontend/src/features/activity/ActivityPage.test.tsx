import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { ActivityPage } from "./ActivityPage";

test("shows activity context, recovery, and focused report actions", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = url.endsWith("/profiles") ? [{ id: "p1", name: "Family world", server_directory: "/srv/family", distribution: "paper", minecraft_version: "1.21.1", loader_version: null, is_fixture: false }]
      : url.endsWith("/notifications") ? { alerts: [{ id: "low-disk-space", kind: "low_disk_space", title: "Disk space is running low", detail: "The data disk is 92% full.", severity: "warning", created_at: "2026-07-21T12:01:00Z", recovery_to: "/system" }], unread_count: 1 }
        : url.endsWith("/notification-preferences") ? { server_crashes: true, failed_backups: true, failed_automations: true, low_disk_space: true, completed_updates: true, show_player_avatars: false, last_seen_at: null }
          : { events: [{ id: "event-1", category: "manual_backup", group: "backup", title: "Manual backup", result: "failed", severity: "danger", detail: "Backup failed because the disk is full", actor: "owner", profile: { id: "p1", name: "Family world" }, created_at: "2026-07-21T12:00:00Z", recovery_to: "/servers/p1/backups", report_url: "/api/v1/activity/event-1/report" }], total: 1, limit: 50, offset: 0 };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(<MemoryRouter><QueryClientProvider client={client}><ActivityPage /></QueryClientProvider></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Activity", level: 1 })).toBeVisible();
  expect(await screen.findByText("Backup failed because the disk is full")).toBeVisible();
  expect(screen.getByText("owner · Family world · backup")).toBeVisible();
  expect(screen.getAllByRole("link", { name: "Open recovery" }).some(link => link.getAttribute("href") === "/servers/p1/backups")).toBe(true);
  expect(screen.getByRole("link", { name: "View incident story" })).toHaveAttribute("href", "/activity?incident=event-1#incident-story");
  expect(screen.getByRole("link", { name: "Download support report" })).toHaveAttribute("href", "/api/v1/activity/event-1/report");
  expect(screen.getByRole("checkbox", { name: /Server crashes/ })).toBeChecked();
  expect(screen.getByRole("button", { name: /What does Mark seen do?/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /How do outcomes and support reports work?/ })).toBeVisible();

  client.clear();
  vi.unstubAllGlobals();
});

test("opens a deep-linked incident story with facts, qualified timing, evidence, and a safe action", async () => {
  const anchor = { id: "event-1", category: "manual_backup", group: "backup", title: "Manual backup", result: "failed", severity: "danger", detail: "Backup failed because the disk is full", actor: "owner", profile: { id: "p1", name: "Family world" }, created_at: "2026-07-21T12:00:00Z", recovery_to: "/servers/p1/backups", report_url: "/api/v1/activity/event-1/report" };
  const settingsFact = { id: "event-0", category: "settings_update", group: "settings", title: "Server settings updated", result: "success", severity: "success", detail: "Changed the view distance", actor: "owner", profile: { id: "p1", name: "Family world" }, created_at: "2026-07-21T11:50:00Z", recovery_to: "/servers/p1/settings", report_url: "/api/v1/activity/event-0/report" };
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = url.includes("/activity/event-1/incident") ? {
      anchor,
      recorded_facts: [settingsFact],
      observed_timing: { label: "Ten minutes apart", detail: "The settings change was recorded ten minutes before the failed backup." },
      possible_explanation: { state: "possible", detail: "The full disk may explain the failed write, but Blockstead has not proven a cause." },
      log_context: { state: "available", detail: "Two application log entries were recorded near this event.", entries: [{ at: "2026-07-21T12:00:01Z", level: "ERROR", logger: "blockstead.backups", message: "No space left on device" }] },
      safe_next_action: { label: "Free storage, then retry", detail: "Review the data disk without deleting the only recovery copy.", to: "/system" },
    } : url.endsWith("/profiles") ? [{ id: "p1", name: "Family world", server_directory: "/srv/family", distribution: "paper", minecraft_version: "1.21.1", loader_version: null, is_fixture: false }]
      : url.endsWith("/notifications") ? { alerts: [], unread_count: 0 }
        : url.endsWith("/notification-preferences") ? { server_crashes: true, failed_backups: true, failed_automations: true, low_disk_space: true, completed_updates: true, show_player_avatars: false, last_seen_at: null }
          : { events: [anchor], total: 1, limit: 50, offset: 0 };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(<MemoryRouter initialEntries={["/activity?profile_id=p1&incident=event-1"]}><QueryClientProvider client={client}><ActivityPage /></QueryClientProvider></MemoryRouter>);

  const story = await screen.findByRole("region", { name: "Manual backup" });
  expect(within(story).getByText("Backup failed because the disk is full")).toBeVisible();
  expect(within(story).getByText("Recorded facts")).toBeVisible();
  expect(within(story).getByText("Ten minutes apart")).toBeVisible();
  expect(within(story).getByText("Possible explanation — not confirmed")).toBeVisible();
  expect(within(story).getByText(/has not proven a cause/)).toBeVisible();
  expect(within(story).getByRole("log", { name: "Log entries near this incident" })).toHaveTextContent("No space left on device");
  expect(within(story).getByRole("link", { name: "Download raw evidence report" })).toHaveAttribute("href", "/api/v1/activity/event-1/report");
  expect(within(story).getByRole("link", { name: "Open next step" })).toHaveAttribute("href", "/system");
  expect(within(story).getByRole("button", { name: /How Blockstead builds this story/ })).toBeVisible();

  fireEvent.click(within(story).getByRole("button", { name: "Close story" }));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Manual backup" })).not.toBeInTheDocument());

  client.clear();
  vi.unstubAllGlobals();
});
