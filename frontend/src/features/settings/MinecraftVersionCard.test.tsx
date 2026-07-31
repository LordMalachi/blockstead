import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { Profile } from "../../api/client";
import { MinecraftVersionCard } from "./MinecraftVersionCard";

const profile: Profile = {
  id: "profile-1",
  name: "Friends SMP",
  server_directory: "/srv/minecraft/friends-smp",
  distribution: "vanilla",
  minecraft_version: null,
  loader_version: null,
  is_fixture: false,
};

function response(body: object) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderCard(current: Profile = profile, fetchMock = vi.fn().mockResolvedValue(response({ ...current, minecraft_version: "1.21.4" }))) {
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { fetchMock, ...render(<QueryClientProvider client={client}><MinecraftVersionCard profile={current} /></QueryClientProvider>) };
}

test("explains what an unrecorded version blocks", () => {
  renderCard();

  expect(screen.getByText("Not recorded")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("could not tell which Minecraft version");
});

test("records a version the owner supplies", async () => {
  const { fetchMock } = renderCard();

  fireEvent.click(screen.getByRole("button", { name: "Record the version" }));
  fireEvent.change(screen.getByLabelText("Minecraft version number"), { target: { value: "1.21.4" } });
  fireEvent.click(screen.getByRole("button", { name: "Save version" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
  const request = calls.find(([url]) => url === "/api/v1/profiles/profile-1/minecraft-version");
  expect(request?.[1].method).toBe("PUT");
  const body = request?.[1].body;
  const sent = JSON.parse(typeof body === "string" ? body : "{}") as Record<string, unknown>;
  expect(sent).toEqual({ minecraft_version: "1.21.4" });
});

test("refuses something that is not a version before asking the server", () => {
  const { fetchMock } = renderCard();

  fireEvent.click(screen.getByRole("button", { name: "Record the version" }));
  fireEvent.change(screen.getByLabelText("Minecraft version number"), { target: { value: "latest please" } });
  fireEvent.click(screen.getByRole("button", { name: "Save version" }));

  expect(screen.getByRole("alert")).toHaveTextContent("Enter a Minecraft version such as 1.21.4.");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("shows a recorded version and offers to correct it", () => {
  renderCard({ ...profile, minecraft_version: "1.20.1" });

  expect(screen.getByText("1.20.1")).toBeVisible();
  expect(screen.getByRole("button", { name: "Change version" })).toBeVisible();
  expect(screen.queryByRole("status")).toBeNull();
});
