import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import App from "./App";
import { clearCsrf, setCsrf } from "./api/client";

test("an expired session returns the owner to the sign-in screen", async () => {
  setCsrf("test-csrf");
  let expired = false;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (expired) {
      return Promise.resolve(new Response(
        JSON.stringify({ error: { code: "AUTHENTICATION_REQUIRED", message: "Sign in again." } }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ));
    }
    const body = url.endsWith("/setup/status") ? { needs_setup: false }
      : url.endsWith("/auth/me") ? { username: "owner" }
        : url.endsWith("/server/state") ? { state: "RUNNING", pid: 4, exit_code: null, reason: "Server reported ready" }
          : url.includes("/provision/versions/") ? { distribution: "vanilla", versions: ["1.21.1"] }
            : [];
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
  }));

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><App /></QueryClientProvider></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Servers", level: 1 })).toBeVisible();

  // The next poll after expiry comes back 401; the dashboard must not keep
  // showing its last good data as if it were live.
  expired = true;
  expect(await screen.findByRole("heading", { name: "Welcome back" }, { timeout: 5000 })).toBeVisible();

  client.clear();
  clearCsrf();
}, 10_000);
