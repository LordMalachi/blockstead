import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { CommandCatalog, PlayersView } from "../../api/client";
import { CommandCenter } from "./CommandCenter";

const catalog: CommandCatalog = {
  schema_version: 1,
  revision: "test",
  source: "curated",
  complete: false,
  commands: [
    {
      id: "give", label: "Give an item", root: "give", category: "Items", description: "Give an item to a player.", safety: "normal",
      arguments: [
        { key: "target", label: "Who", kind: "player", required: true, source: "players" },
        { key: "item", label: "Item", kind: "resource", required: true, options: [
          { value: "minecraft:diamond", label: "Diamond", icon: "◆" },
          { value: "minecraft:apple", label: "Apple", icon: "●" },
          { value: "minecraft:bread", label: "Bread" },
          { value: "minecraft:coal", label: "Coal" },
          { value: "minecraft:torch", label: "Torch" },
          { value: "minecraft:shield", label: "Shield" },
        ] },
        { key: "amount", label: "How many", kind: "integer", required: false, suggestions: [1, 64] },
      ],
    },
    {
      id: "ban", label: "Ban a player", root: "ban", category: "Moderation", description: "Ban a player.", safety: "danger",
      arguments: [{ key: "target", label: "Player", kind: "player", required: true, source: "players", allow_selectors: false }],
    },
  ],
};

const players: PlayersView = {
  allowlist: { present: true, readable: true, players: [{ name: "Alex_Fixture", uuid: null, level: null, reason: null }] },
  operators: { present: true, readable: true, players: [] },
  bans: { present: true, readable: true, players: [] },
};

function setup() {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    requests.push({ url, init });
    if (url.includes("/commands")) return Promise.resolve(new Response(JSON.stringify(catalog), { status: 200, headers: { "Content-Type": "application/json" } }));
    if (url.includes("/players")) return Promise.resolve(new Response(JSON.stringify(players), { status: 200, headers: { "Content-Type": "application/json" } }));
    return Promise.resolve(new Response(JSON.stringify({ command: "give Alex_Fixture minecraft:diamond 64" }), { status: 202, headers: { "Content-Type": "application/json" } }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><CommandCenter profileId="profile-1" running /></QueryClientProvider>);
  return requests;
}

test("searches large options, previews, and submits a guided command", async () => {
  const requests = setup();
  await userEvent.click(await screen.findByRole("button", { name: /Give an item/ }));
  await userEvent.type(screen.getByLabelText("Who"), "Alex_Fixture");
  await userEvent.type(screen.getByLabelText("Item"), "diamond");
  await userEvent.click(screen.getByRole("option", { name: /Diamond minecraft:diamond/ }));
  await userEvent.click(screen.getByRole("button", { name: "64" }));

  expect(screen.getByText("give Alex_Fixture minecraft:diamond 64")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Review and send" }));
  await waitFor(() => expect(requests.some(request => request.url.endsWith("/api/v1/server/guided-command"))).toBe(true));
  const sent = requests.find(request => request.url.endsWith("/api/v1/server/guided-command"));
  const body = sent?.init?.body;
  expect(typeof body).toBe("string");
  expect(JSON.parse(typeof body === "string" ? body : "{}")).toMatchObject({ command_id: "give", values: { target: "Alex_Fixture", item: "minecraft:diamond", amount: "64" }, confirmed: false });
});

test("requires a second click for a dangerous command", async () => {
  const requests = setup();
  await userEvent.click(await screen.findByRole("button", { name: /Ban a player/ }));
  await userEvent.type(screen.getByLabelText("Player"), "Alex_Fixture");
  await userEvent.click(screen.getByRole("button", { name: "Review and send" }));
  expect(screen.getByText("Check this command before sending it.")).toBeVisible();
  expect(requests.filter(request => request.url.endsWith("/api/v1/server/guided-command"))).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "Confirm and send" }));
  await waitFor(() => expect(requests.filter(request => request.url.endsWith("/api/v1/server/guided-command"))).toHaveLength(1));
});
