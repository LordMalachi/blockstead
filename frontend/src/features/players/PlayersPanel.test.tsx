import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { PlayersPanel } from "./PlayersPanel";
import type { PlayersView } from "../../api/client";

const view: PlayersView = {
  allowlist: { present: true, readable: true, players: [{ name: "Alex_Fixture", uuid: null, level: null, reason: null }, { name: "Steve_Fixture", uuid: null, level: null, reason: null }] },
  operators: { present: true, readable: true, players: [{ name: "Alex_Fixture", uuid: null, level: 4, reason: null }] },
  bans: { present: false, readable: false, players: [] },
};

function renderPanel(running: boolean) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(view), { status: 200, headers: { "Content-Type": "application/json" } })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PlayersPanel profileId="profile-1" running={running} /></QueryClientProvider>);
}

test("lists players from server files and labels missing files", async () => {
  renderPanel(false);
  expect(await screen.findByText("Steve_Fixture")).toBeVisible();
  expect(screen.getByText("level 4")).toBeVisible();
  expect(screen.getByText("Not created yet.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  expect(screen.getByText(/Start the server to apply player actions/)).toBeVisible();
});

test("enables guided actions while the server runs", async () => {
  renderPanel(true);
  expect((await screen.findAllByText("Alex_Fixture")).length).toBeGreaterThan(0);
  expect(screen.getByLabelText("Player name")).toBeEnabled();
  expect(screen.getByLabelText("Action")).toBeEnabled();
});
