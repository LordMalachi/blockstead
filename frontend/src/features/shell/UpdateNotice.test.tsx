import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { UpdateNotice } from "./UpdateNotice";
import type { UpdateStatus } from "../../api/client";

const current: UpdateStatus = {
  build: { version: "0.1.0", commit: "a".repeat(40), short_commit: "aaaaaaa", committed_at: "2026-07-19T12:00:00+00:00", label: "0.1.0 (aaaaaaa)", source: "git" },
  automatic: true,
  supported: true,
  decision: "current",
  latest: null,
  checked_at: "2026-07-20T12:00:00+00:00",
  error: null,
  installing: false,
  last_result: null,
  announcement: null,
};

function serve(status: UpdateStatus) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(
    JSON.stringify(status), { status: 200, headers: { "Content-Type": "application/json" } },
  ))));
}

function renderNotice() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><UpdateNotice /></QueryClientProvider>);
  return client;
}

test("an up-to-date installation says nothing at all", async () => {
  serve(current);
  const client = renderNotice();

  // Nothing to announce and nothing pending, so the shell stays quiet.
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();

  client.clear();
  vi.unstubAllGlobals();
});

test("an update waiting on players explains why it has not installed", async () => {
  serve({
    ...current,
    decision: "waiting_for_players",
    latest: { commit: "b".repeat(40), short_commit: "bbbbbbb", committed_at: "2026-07-20T12:00:00+00:00", summary: "Add a thing" },
  });
  const client = renderNotice();

  expect(await screen.findByRole("status")).toHaveTextContent(
    /will install once the Minecraft server is empty/,
  );

  client.clear();
  vi.unstubAllGlobals();
});

test("an installation in progress warns that the dashboard will restart", async () => {
  serve({ ...current, installing: true });
  const client = renderNotice();

  expect(await screen.findByRole("status")).toHaveTextContent(/dashboard will restart on its own/);

  client.clear();
  vi.unstubAllGlobals();
});

test("a copy that cannot update itself says so instead of pretending", async () => {
  serve({
    ...current,
    supported: false,
    decision: "manual",
    latest: { commit: "b".repeat(40), short_commit: "bbbbbbb", committed_at: "2026-07-20T12:00:00+00:00", summary: "Add a thing" },
  });
  const client = renderNotice();

  expect(await screen.findByRole("status")).toHaveTextContent(/cannot update itself/);

  client.clear();
  vi.unstubAllGlobals();
});

test("a completed update announces the version the owner is now on", async () => {
  serve({
    ...current,
    build: { ...current.build, commit: "b".repeat(40), short_commit: "bbbbbbb", label: "0.1.0 (bbbbbbb)" },
    announcement: {
      version: "0.1.0",
      label: "0.1.0 (bbbbbbb)",
      commit: "b".repeat(40),
      short_commit: "bbbbbbb",
      previous_commit: "a".repeat(40),
      summary: "Add a thing",
    },
  });
  const client = renderNotice();

  const dialog = await screen.findByRole("dialog", { name: "You are on 0.1.0 (bbbbbbb)" });
  expect(dialog).toBeVisible();
  expect(screen.getByText(/Add a thing/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Got it" })).toBeEnabled();

  client.clear();
  vi.unstubAllGlobals();
});

test("dismissing the announcement tells the server it was seen", async () => {
  const status = {
    ...current,
    announcement: {
      version: "0.1.0",
      label: "0.1.0 (bbbbbbb)",
      commit: "b".repeat(40),
      short_commit: "bbbbbbb",
      previous_commit: "a".repeat(40),
      summary: null,
    },
  };
  const calls: Array<{ url: string; method: string }> = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET" });
    const body = init?.method === "POST" ? { ...status, announcement: null } : status;
    return Promise.resolve(new Response(
      JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } },
    ));
  }));
  const client = renderNotice();

  fireEvent.click(await screen.findByRole("button", { name: "Got it" }));

  await waitFor(() => {
    expect(calls.some(call => call.url.endsWith("/updates/acknowledge") && call.method === "POST")).toBe(true);
  });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  client.clear();
  vi.unstubAllGlobals();
});
