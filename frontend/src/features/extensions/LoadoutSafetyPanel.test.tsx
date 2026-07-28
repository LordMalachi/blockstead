import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, vi } from "vitest";
import { LoadoutSafetyPanel, type LoadoutLockfileReview, type LoadoutTestResult } from "./LoadoutSafetyPanel";

const failedTest: LoadoutTestResult = {
  run_id: "test-run-1",
  status: "failed",
  summary: "A recently installed mod stopped startup.",
  log_tail: Array.from({ length: 60 }, (_, index) => `log line ${index + 1}`),
  log_lines_truncated: false,
  quarantined: [{ file_name: "broken-mod.jar", reason: "The loader reported an entrypoint failure." }],
  retry_allowed: true,
};

const passedTest: LoadoutTestResult = {
  run_id: "test-run-2",
  status: "passed",
  summary: "The server reached a ready state with player connections closed.",
  log_tail: ["Loading mods", "Done"],
  log_lines_truncated: false,
  quarantined: [],
  retry_allowed: false,
};

const lockfileReview: LoadoutLockfileReview = {
  review_id: "lock-review-1",
  minecraft_version: "1.21.1",
  distribution: "fabric",
  loader_version: "0.16.10",
  changes: [
    { file_name: "lithium.jar", action: "update", detail: "1.0.0 → 1.1.0" },
    { file_name: "server-helper.jar", action: "unavailable", detail: "No matching Fabric release was found." },
  ],
  exclusions: ["spark.jar is server-only."],
  manual_requirements: ["Download private-mod.jar from its publisher."],
  warnings: ["One project cannot be matched to a trusted catalog source."],
  blockers: [],
  expires_in_seconds: 600,
};

const playerPackReview = {
  review_id: "0123456789abcdef",
  file_name: "family-players.mrpack",
  dependencies: { minecraft: "1.21.1", "fabric-loader": "0.16.10" },
  included: [{ file_name: "client.jar" }],
  manual_requirements: [{ file_name: "private-mod.jar", reason: "Download it manually." }],
  disclosures: [],
  excluded: [{ file_name: "spark.jar", reason: "Known server-only extension." }],
};

function json(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel({
  stopped = true,
  recentlyInstalledBatchIds = ["batch-a", "batch-b"],
}: {
  stopped?: boolean;
  recentlyInstalledBatchIds?: readonly string[];
} = {}) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <LoadoutSafetyPanel
        profileId="profile-1"
        stopped={stopped}
        recentlyInstalledBatchIds={recentlyInstalledBatchIds}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("runs a private test, bounds logs, quarantines failures, and retries", async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(json(failedTest))
    .mockResolvedValueOnce(json(passedTest));
  vi.stubGlobal("fetch", fetch);
  renderPanel();

  expect(screen.getByText(/Player connections stay closed/i)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Run safe test start" }));

  expect(await screen.findByText("Private test failed")).toBeVisible();
  expect(screen.getByText("broken-mod.jar")).toBeVisible();
  expect(screen.getByText(/disabled without changing the world/i)).toBeVisible();
  expect(screen.getByLabelText("Private test startup logs")).not.toHaveTextContent("log line 1\n");
  expect(screen.getByLabelText("Private test startup logs")).toHaveTextContent("log line 60");
  expect(screen.getByText("Showing only the most recent 50 log lines.")).toBeVisible();

  expect(fetch).toHaveBeenNthCalledWith(
    1,
    "/api/v1/profiles/profile-1/loadout/test-start",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ recent_batch_ids: ["batch-a", "batch-b"], retry_of: null }),
    }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Retry without quarantined files" }));
  expect(await screen.findByText("Private test passed")).toBeVisible();
  expect(fetch).toHaveBeenNthCalledWith(
    2,
    "/api/v1/profiles/profile-1/loadout/test-start",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ recent_batch_ids: ["batch-a", "batch-b"], retry_of: "test-run-1" }),
    }),
  );
});

test("requires the normal server to be stopped before safe testing", () => {
  vi.stubGlobal("fetch", vi.fn());
  renderPanel({ stopped: false });

  expect(screen.getByRole("button", { name: "Run safe test start" })).toBeDisabled();
  expect(screen.getByText("Stop the server before running a private test start.")).toBeVisible();
});

test("downloads lockfiles and player packs with explicit sharing caveats", async () => {
  const fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    return Promise.resolve(
      url.endsWith("/loadout/player-pack/review")
        ? json(playerPackReview)
        : new Response("artifact", { status: 200 }),
    );
  });
  vi.stubGlobal("fetch", fetch);
  const createObjectURL = vi.fn().mockReturnValue("blob:blockstead");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  renderPanel();

  fireEvent.click(screen.getByRole("button", { name: "Download lockfile" }));
  expect(await screen.findByText("Loadout lockfile downloaded.")).toBeVisible();
  expect(fetch).toHaveBeenCalledWith("/api/v1/profiles/profile-1/loadout/lockfile");

  fireEvent.click(screen.getByRole("button", { name: "Review player pack" }));
  expect(await screen.findByRole("heading", { name: "family-players.mrpack" })).toBeVisible();
  expect(screen.getByText("client.jar")).toBeVisible();
  expect(screen.getByText("private-mod.jar")).toBeVisible();
  expect(screen.getByText("spark.jar")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Download reviewed player pack" }));
  expect(await screen.findByText(/Player pack downloaded/i)).toBeVisible();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/loadout/player-pack?review_id=0123456789abcdef",
  );
  expect(screen.getByText("Server-only mods and plugins are excluded.")).toBeVisible();
  expect(screen.getByText(/cannot be redistributed are listed as manual requirements/i)).toBeVisible();
  expect(screen.getByText(/matching launcher, Minecraft version, and loader/i)).toBeVisible();
  expect(createObjectURL).toHaveBeenCalledTimes(2);
  expect(revokeObjectURL).toHaveBeenCalledTimes(2);
  expect(click).toHaveBeenCalledTimes(2);
});

test("uploads a lockfile for review without offering to apply it", async () => {
  const fetch = vi.fn().mockResolvedValue(json(lockfileReview));
  vi.stubGlobal("fetch", fetch);
  renderPanel();

  const file = new File(["{}"], "friends-server.lock.json", { type: "application/json" });
  fireEvent.change(screen.getByLabelText("Choose a loadout lockfile"), { target: { files: [file] } });

  expect(await screen.findByRole("heading", { name: "Lockfile comparison" })).toBeVisible();
  expect(screen.getByText("lithium.jar")).toBeVisible();
  expect(screen.getByText("update · 1.0.0 → 1.1.0")).toBeVisible();
  expect(screen.getByText("spark.jar is server-only.")).toBeVisible();
  expect(screen.getByText("Download private-mod.jar from its publisher.")).toBeVisible();
  expect(screen.getByText("No changes have been applied.")).toBeVisible();
  expect(screen.queryByRole("button", { name: /apply|install|restore/i })).not.toBeInTheDocument();

  await waitFor(() => expect(fetch).toHaveBeenCalled());
  const calls = fetch.mock.calls as unknown as Array<[string, RequestInit]>;
  const request = calls.find(([url]) => url === "/api/v1/profiles/profile-1/loadout/lockfile/review");
  expect(request?.[1].method).toBe("POST");
  expect((request?.[1].body as FormData).get("file")).toBe(file);
});
