import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import type { Profile } from "../../api/client";
import { ServerLayout } from "./ServerLayout";

const first: Profile = { id: "server-1", name: "Family", server_directory: "/srv/minecraft/family", distribution: "paper", minecraft_version: "1.21.1", loader_version: null, paper_build: 205, is_fixture: false };
const second: Profile = { id: "server-2", name: "Creative", server_directory: "/srv/minecraft/creative", distribution: "paper", minecraft_version: "1.21.1", loader_version: null, is_fixture: false };

test("updates the active-server picker when the shared profile list changes", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = url.endsWith("/profiles")
      ? [first, second]
      : { state: "STOPPED", pid: null, exit_code: null, reason: "No server is running." };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/servers/server-1/overview"]}>
        <Routes>
          <Route path="/servers/:profileId/*" element={<ServerLayout />}>
            <Route path="overview" element={<p>Overview</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const picker = await screen.findByLabelText("Active server");
  expect(screen.getByText("Paper · build 205 · Minecraft 1.21.1")).toBeVisible();
  expect(screen.getByRole("option", { name: /Creative/ })).toBeVisible();
  client.setQueryData<Profile[]>(["profiles"], [first]);

  await waitFor(() => expect(screen.queryByRole("option", { name: /Creative/ })).not.toBeInTheDocument());
  expect(picker).toHaveValue("server-1");
});
