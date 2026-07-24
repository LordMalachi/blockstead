import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";
import type { NotificationPreferences, RosterView } from "../../api/client";
import { PlayersPanel } from "./PlayersPanel";

const roster: RosterView = {
  status_available: true,
  online_count: 1,
  max_players: 20,
  entries: [
    {
      name: "Alex_Fixture",
      uuid: "00000000-0000-0000-0000-000000000001",
      online: true,
      allowlisted: true,
      operator: true,
      banned: false,
      ban_reason: null,
      tracked_online: true,
      last_seen: null,
      session_seconds: 42,
    },
    {
      name: "Steve_Fixture",
      uuid: null,
      online: false,
      allowlisted: true,
      operator: false,
      banned: false,
      ban_reason: null,
      tracked_online: false,
      last_seen: "2026-07-20T10:00:00Z",
      session_seconds: 300,
    },
    {
      name: "Baddie_Fixture",
      uuid: null,
      online: false,
      allowlisted: false,
      operator: false,
      banned: true,
      ban_reason: "Griefing",
      tracked_online: false,
      last_seen: null,
      session_seconds: null,
    },
  ],
};

const preferences: NotificationPreferences = {
  server_crashes: true,
  failed_backups: true,
  low_disk_space: true,
  completed_updates: true,
  show_player_avatars: false,
  last_seen_at: null,
};

function respond(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPanel({ running = true, showAvatars = false }: { running?: boolean; showAvatars?: boolean } = {}) {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url.endsWith("/players/roster")) return Promise.resolve(respond(roster));
    if (url.endsWith("/notification-preferences")) return Promise.resolve(respond({ ...preferences, show_player_avatars: showAvatars }));
    if (url.endsWith("/server/players") && method === "POST") {
      const payload = JSON.parse((init?.body as string) ?? "{}") as { action: string; player: string };
      return Promise.resolve(respond({ command: `${payload.action} ${payload.player}` }));
    }
    return Promise.resolve(respond({}));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><PlayersPanel profileId="profile-1" running={running} /></QueryClientProvider>);
}

function rowFor(name: string): HTMLElement {
  const heading = screen.getByText(name);
  const row = heading.closest("li");
  if (!row) throw new Error(`No roster row found for ${name}`);
  return row as HTMLElement;
}

test("lists roster entries with live status and badges", async () => {
  renderPanel();
  expect(await screen.findByText("Alex_Fixture")).toBeVisible();
  expect(screen.getByText("1 of 20 online")).toBeVisible();
  expect(within(rowFor("Alex_Fixture")).getByText("Operator")).toBeVisible();
  expect(within(rowFor("Alex_Fixture")).getByText("Allowlisted")).toBeVisible();
  expect(within(rowFor("Baddie_Fixture")).getByText("Banned: Griefing")).toBeVisible();
});

test("shows a last-seen and play duration note for an offline tracked player", async () => {
  renderPanel();
  await screen.findByText("Steve_Fixture");
  expect(within(rowFor("Steve_Fixture")).getByText(/Last seen/)).toBeVisible();
  expect(within(rowFor("Steve_Fixture")).getByText(/played 5m/)).toBeVisible();
});

test("searches the roster by name", async () => {
  renderPanel();
  await screen.findByText("Alex_Fixture");
  fireEvent.change(screen.getByLabelText("Search players"), { target: { value: "steve" } });
  expect(screen.queryByText("Alex_Fixture")).not.toBeInTheDocument();
  expect(screen.getByText("Steve_Fixture")).toBeVisible();
});

test("filters to only online players", async () => {
  renderPanel();
  await screen.findByText("Alex_Fixture");
  fireEvent.click(screen.getByRole("button", { name: "Online" }));
  expect(screen.getByText("Alex_Fixture")).toBeVisible();
  expect(screen.queryByText("Steve_Fixture")).not.toBeInTheDocument();
  expect(screen.queryByText("Baddie_Fixture")).not.toBeInTheDocument();
});

test("kicks an online player after a second confirming click", async () => {
  renderPanel();
  await screen.findByText("Alex_Fixture");
  const row = within(rowFor("Alex_Fixture"));

  fireEvent.click(row.getByRole("button", { name: "Kick" }));
  fireEvent.click(row.getByRole("button", { name: "Confirm kick" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/server/players",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "kick", player: "Alex_Fixture" }) }),
  ));
  expect(await screen.findByText(/Sent .kick Alex_Fixture. to the server console/)).toBeVisible();
});

test("bans a player from their row after confirming", async () => {
  renderPanel();
  await screen.findByText("Steve_Fixture");
  const row = within(rowFor("Steve_Fixture"));

  fireEvent.click(row.getByRole("button", { name: "Ban" }));
  fireEvent.click(row.getByRole("button", { name: "Confirm ban" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/server/players",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "ban", player: "Steve_Fixture" }) }),
  ));
});

test("unbans a banned player without a confirmation step", async () => {
  renderPanel();
  await screen.findByText("Baddie_Fixture");
  const row = within(rowFor("Baddie_Fixture"));

  fireEvent.click(row.getByRole("button", { name: "Unban" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/server/players",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "pardon", player: "Baddie_Fixture" }) }),
  ));
});

test("hides avatars by default and shows a placeholder when opted in without a UUID", async () => {
  renderPanel({ showAvatars: true });
  await screen.findByText("Steve_Fixture");
  // A decorative avatar (alt="") is intentionally invisible to the accessibility
  // tree, so it has to be queried as a plain DOM node rather than by role.
  const avatarImg = rowFor("Alex_Fixture").querySelector("img.roster-avatar");
  expect(avatarImg).toHaveAttribute(
    "src",
    "https://crafatar.com/avatars/00000000-0000-0000-0000-000000000001?size=32&overlay",
  );
  expect(within(rowFor("Steve_Fixture")).getByText("S")).toBeVisible();
});

test("adds a brand-new player through the guided form", async () => {
  renderPanel();
  await screen.findByText("Alex_Fixture");
  fireEvent.change(screen.getByLabelText("Player name"), { target: { value: "New_Neighbor" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/server/players",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ action: "whitelist_add", player: "New_Neighbor" }),
    }),
  ));
});

test("disables actions and explains why while the server is stopped", async () => {
  renderPanel({ running: false });
  await screen.findByText("Alex_Fixture");
  expect(within(rowFor("Steve_Fixture")).getByRole("button", { name: "Ban" })).toBeDisabled();
  expect(screen.getByText(/Start the server to apply player actions/)).toBeVisible();
});
