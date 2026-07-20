import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { UpdatePanel } from "./UpdatePanel";
import type { UpdateStatus } from "../../api/client";

const status: UpdateStatus = {
  build: { version: "0.1.0", commit: "a".repeat(40), short_commit: "aaaaaaa", committed_at: "2026-07-19T12:00:00+00:00", label: "0.1.0 (aaaaaaa)", source: "git" },
  automatic: true,
  supported: true,
  decision: "current",
  latest: { commit: "a".repeat(40), short_commit: "aaaaaaa", committed_at: "2026-07-19T12:00:00+00:00", summary: "Add a thing" },
  checked_at: "2026-07-20T12:00:00+00:00",
  error: null,
  installing: false,
  last_result: null,
  announcement: null,
};

function renderPanel(body: UpdateStatus) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(
    JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } },
  ))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><UpdatePanel /></QueryClientProvider>);
  return client;
}

test("the panel shows which build is installed and when it last looked", async () => {
  const client = renderPanel(status);

  expect(await screen.findByText("0.1.0 (aaaaaaa)")).toBeVisible();
  expect(screen.getByText("Up to date")).toBeVisible();
  expect(screen.getByRole("button", { name: "Check now" })).toBeEnabled();

  client.clear();
  vi.unstubAllGlobals();
});

test("a server with players is described as waiting rather than stuck", async () => {
  const client = renderPanel({ ...status, decision: "waiting_for_players" });

  expect(await screen.findByText("Waiting for players to leave")).toBeVisible();

  client.clear();
  vi.unstubAllGlobals();
});

test("an installation without the helper says automatic updates are unavailable", async () => {
  const client = renderPanel({ ...status, supported: false, decision: "manual" });

  expect(await screen.findByText("Not available here")).toBeVisible();
  expect(screen.getByText(/cannot update itself/)).toBeVisible();

  client.clear();
  vi.unstubAllGlobals();
});

test("a failed update is reported instead of being hidden", async () => {
  const client = renderPanel({
    ...status,
    last_result: { state: "failed", detail: "The update did not install cleanly, so the previous version was kept.", at: "2026-07-20T12:00:00+00:00" },
  });

  expect(await screen.findByText(/previous version was kept/)).toBeVisible();

  client.clear();
  vi.unstubAllGlobals();
});

test("a check that cannot reach GitHub explains itself", async () => {
  const client = renderPanel({ ...status, error: "Blockstead could not reach GitHub to check for updates." });

  expect(await screen.findByText("Blockstead could not reach GitHub to check for updates.")).toBeVisible();

  client.clear();
  vi.unstubAllGlobals();
});

test("the check button is unavailable while an update is installing", async () => {
  const client = renderPanel({ ...status, installing: true, decision: "install" });

  await screen.findByText("Installing now");
  expect(screen.getByRole("button", { name: "Check now" })).toBeDisabled();

  client.clear();
  vi.unstubAllGlobals();
});
