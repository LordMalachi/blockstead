import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type {
  MaintenanceBooking,
  MaintenanceCatalog,
  MaintenancePlan,
  UpgradeReview,
} from "../../api/client";
import { MaintenancePanel } from "./MaintenancePanel";

const catalog: MaintenanceCatalog = {
  version: "2026.07.1",
  changes: [
    {
      id: "world_files",
      title: "Edit or replace world files",
      summary: "Change files inside the world folder through the file workspace.",
      workspace: "files",
      requires_stopped_server: true,
      version_changing: false,
      destructive: true,
      restart_expectation: "required",
      checks: ["Who is connected right now", "Whether a verified protection point exists"],
    },
    {
      id: "server_upgrade",
      title: "Upgrade the server or loader version",
      summary: "Move this server to a different Minecraft or loader version.",
      workspace: "overview",
      requires_stopped_server: true,
      version_changing: true,
      destructive: true,
      restart_expectation: "required",
      checks: ["Whether a verified upgrade source is available"],
    },
  ],
};

const readyPlan: MaintenancePlan = {
  catalog_version: "2026.07.1",
  plan_id: "abc123def456",
  profile_id: "profile-1",
  change: catalog.changes[0],
  readiness: "ready_with_warnings",
  headline: "Edit or replace world files is possible on Homestead, with things to know",
  detail: "Nothing blocks this change, but needs attention: protection point.",
  findings: [
    {
      id: "connected-players",
      label: "Connected players",
      status: "unknown",
      detail: "Minecraft did not answer Blockstead's local status check.",
      recommendation: "Announce the change in the console before you begin.",
    },
    {
      id: "protection-point",
      label: "Protection point",
      status: "attention",
      detail: "This server has no completed backup.",
      recommendation: null,
    },
  ],
  steps: [
    {
      id: "backup",
      label: "Create a backup and verify it",
      detail: "This is the only way back from this change.",
      requirement: "required",
      performed_by: "owner",
      route: "/servers/profile-1/backups",
    },
    {
      id: "stop",
      label: "Stop the server safely",
      detail: "Blockstead applies this change only to a stopped server.",
      requirement: "not_needed",
      performed_by: "owner",
      route: "/servers/profile-1/console",
    },
  ],
  protection: {
    verified: false,
    detail: "This server has no completed backup to fall back on.",
    backup_id: null,
    created_at: null,
    age_hours: null,
  },
  restart: "required",
  restart_detail: "This change does not take effect until the server starts again.",
  blockers: [],
  reviewed_at: "2026-07-24T20:00:00+00:00",
};

const blockedPlan: MaintenancePlan = {
  ...readyPlan,
  plan_id: "999888777666",
  change: catalog.changes[1],
  readiness: "blocked",
  headline: "Blockstead cannot call this change safe on Homestead yet",
  detail: "One or more checks came back as a stop.",
  findings: [
    {
      id: "compatibility",
      label: "Compatibility limits",
      status: "blocked",
      detail: "Blockstead has no verified upgrade source for Fabric.",
      recommendation: "Upgrade this server with its own installer, then re-import the folder.",
    },
  ],
  blockers: ["Upgrade this server with its own installer, then re-import the folder."],
};

const upgradeReview: UpgradeReview = {
  distribution: "vanilla",
  distribution_label: "Vanilla Minecraft",
  current_version: "1.21.4",
  source: "available",
  source_detail: "812 published Vanilla Minecraft releases were read.",
  up_to_date: false,
  latest_version: "1.21.6",
  candidates: [
    {
      minecraft_version: "1.21.6",
      step: "patch",
      required_java_major: 21,
      java_available: true,
      installable: true,
      detail: "A patch step from 1.21.4. Blockstead can download and verify this release.",
    },
    {
      minecraft_version: "1.21.5",
      step: "patch",
      required_java_major: 21,
      java_available: false,
      installable: false,
      detail: "This release needs Java 21, and no matching runtime was found on this computer.",
    },
  ],
  installable_here: true,
  install_detail: "Blockstead keeps the previous jar so the change can be undone.",
  warnings: ["2 published entries could not be ordered and were left out of this comparison."],
};

const currentReview: UpgradeReview = {
  ...upgradeReview,
  up_to_date: true,
  current_version: "1.21.6",
  candidates: [],
  warnings: [],
};

const booking: MaintenanceBooking = {
  id: "event-1",
  profile_id: "profile-1",
  run_at: "2026-07-25T02:00",
  plan_id: "abc123def456",
  change_id: "world_files",
  only_when_empty: true,
  backup_before_stop: true,
  detail: "Blockstead will stop Homestead at 2026-07-25T02:00 after a verified backup.",
};
const appliedUpgrade = {
  minecraft_version: "1.21.6",
  loader_version: null,
  recovery_id: "abcdef1234567890abcdef12",
  restart_required: true as const,
  detail: "Homestead now uses 1.21.6. The previous launch file is preserved.",
};

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderPanel({
  plan = readyPlan,
  review = upgradeReview,
  scheduleResponse = () => respond(booking, 201),
}: {
  plan?: MaintenancePlan;
  review?: UpgradeReview;
  scheduleResponse?: () => Response;
} = {}) {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.endsWith("/profiles")) return Promise.resolve(respond([{ id: "profile-1", name: "Homestead", server_directory: "/servers/home", distribution: "vanilla", minecraft_version: "1.21.1", loader_version: null, is_fixture: false }]));
    if (url.includes("/maintenance/preflight")) return Promise.resolve(respond(plan));
    if (url.includes("/maintenance/schedule")) return Promise.resolve(scheduleResponse());
    if (url.includes("/maintenance/upgrades/apply")) return Promise.resolve(respond(appliedUpgrade));
    if (url.includes("/maintenance/upgrades/recovery")) return Promise.resolve(respond({ detail: "The previous launch file was restored. The world was not rolled back." }));
    if (url.includes("/maintenance/upgrades")) return Promise.resolve(respond(review));
    return Promise.resolve(respond(catalog));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><MaintenancePanel profileId="profile-1" /></MemoryRouter>
    </QueryClientProvider>,
  );
}

async function reviewWorldFiles() {
  fireEvent.click(await screen.findByRole("radio", { name: /Edit or replace world files/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run the preflight" }));
}

test("lists the reviewable changes and states which need a stopped server", async () => {
  renderPanel();
  expect(await screen.findByText("Edit or replace world files")).toBeVisible();
  expect(screen.getAllByText(/Stopped server only/)).toHaveLength(2);
});

test("a missing maintenance API explains the version mismatch and offers recovery", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.endsWith("/profiles")) return Promise.resolve(respond([]));
    return Promise.resolve(respond(
      { error: { code: "NOT_FOUND", message: "That API route was not found." } },
      404,
    ));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><MaintenancePanel profileId="profile-1" /></MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("Maintenance needs a matching Blockstead update")).toBeVisible();
  expect(screen.getByText(/not a Minecraft or mod error/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Open diagnostics" })).toHaveAttribute("href", "/system#diagnostics");
});

test("running the preflight does not change anything until the owner asks", async () => {
  renderPanel();
  await screen.findByText("Edit or replace world files");
  expect(fetch).not.toHaveBeenCalledWith(
    expect.stringContaining("/maintenance/preflight"),
    expect.anything(),
  );

  fireEvent.click(screen.getByRole("radio", { name: /Edit or replace world files/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Run the preflight" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/maintenance/preflight",
    expect.objectContaining({ method: "POST" }),
  ));
});

test("shows every finding, including the ones Blockstead could not check", async () => {
  renderPanel();
  fireEvent.click(await screen.findByRole("radio", { name: /Edit or replace world files/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run the preflight" }));

  expect(await screen.findByText("Connected players")).toBeVisible();
  expect(screen.getByText("Could not check")).toBeVisible();
  expect(screen.getByText("Announce the change in the console before you begin.")).toBeVisible();
});

test("a risky change shows a required protection step and the restart expectation", async () => {
  renderPanel();
  fireEvent.click(await screen.findByRole("radio", { name: /Edit or replace world files/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run the preflight" }));

  const steps = await screen.findByRole("list", { name: "Reviewed plan" });
  expect(steps).toHaveTextContent("Create a backup and verify it");
  expect(steps).toHaveTextContent("Required");
  expect(screen.getByText("Stop and restart expectation")).toBeVisible();
  expect(screen.getByText("This change does not take effect until the server starts again.")).toBeVisible();
});

test("an unverified protection point is never described as a way back", async () => {
  renderPanel();
  fireEvent.click(await screen.findByRole("radio", { name: /Edit or replace world files/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run the preflight" }));

  expect(await screen.findByText(/no verified way back from this change yet/)).toBeVisible();
});

test("a blocked change shows the blocker instead of a plan to follow", async () => {
  renderPanel({ plan: blockedPlan });
  fireEvent.click(await screen.findByRole("radio", { name: /Upgrade the server or loader version/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run the preflight" }));

  expect(await screen.findByText("Resolve this first")).toBeVisible();
  expect(screen.queryByRole("list", { name: "Reviewed plan" })).toBeNull();
  expect(screen.getByText("Blockstead has no verified upgrade source for Fabric.")).toBeVisible();
  // A blocked plan is not bookable.
  expect(screen.queryByRole("button", { name: "Schedule this plan" })).toBeNull();
});

test("published releases are only fetched for the upgrade review", async () => {
  renderPanel();
  await screen.findByText("Edit or replace world files");
  fireEvent.click(screen.getByRole("radio", { name: /Edit or replace world files/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Run the preflight" })).toBeVisible());
  expect(fetch).not.toHaveBeenCalledWith(
    expect.stringContaining("/maintenance/upgrades"),
    expect.anything(),
  );

  fireEvent.click(screen.getByRole("radio", { name: /Upgrade the server or loader version/ }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/maintenance/upgrades"),
    expect.anything(),
  ));
});

test("the release list separates what is published from what can be installed", async () => {
  renderPanel();
  fireEvent.click(await screen.findByRole("radio", { name: /Upgrade the server or loader version/ }));

  const releases = await screen.findByRole("list", { name: "Newer published releases" });
  expect(releases).toHaveTextContent("1.21.6");
  expect(releases).toHaveTextContent("Blockstead can install");
  expect(releases).toHaveTextContent("Not installable here");
  // Entries the source could not order are disclosed, not silently dropped.
  expect(screen.getByText(/could not be ordered/)).toBeVisible();
});

test("a server on the newest release is told so instead of being offered an upgrade", async () => {
  renderPanel({ review: currentReview });
  fireEvent.click(await screen.findByRole("radio", { name: /Upgrade the server or loader version/ }));

  expect(await screen.findByText(/newest published Vanilla Minecraft release/)).toBeVisible();
  expect(screen.queryByRole("list", { name: "Newer published releases" })).toBeNull();
});

test("applies a reviewed upgrade only with fresh verified protection and offers recovery", async () => {
  const upgradePlan: MaintenancePlan = {
    ...readyPlan,
    plan_id: "1234567890abcdef",
    change: catalog.changes[1],
    readiness: "ready",
    protection: {
      verified: true,
      detail: "Fresh verified backup.",
      backup_id: "backup-1",
      created_at: "2026-07-26T12:00:00Z",
      age_hours: 1,
    },
  };
  renderPanel({ plan: upgradePlan });
  fireEvent.click(await screen.findByRole("radio", { name: /Upgrade the server or loader version/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run the preflight" }));

  fireEvent.click(await screen.findByRole("button", { name: "Upgrade to 1.21.6" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/maintenance/upgrades/apply",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ minecraft_version: "1.21.6", plan_id: "1234567890abcdef" }),
    }),
  ));
  expect(await screen.findByText(/previous launch file is preserved/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Restore previous launch file" })).toBeVisible();
});

test("a reviewed plan can be booked as a maintenance window", async () => {
  renderPanel();
  await reviewWorldFiles();
  fireEvent.click(await screen.findByRole("button", { name: "Schedule this plan" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/maintenance/schedule",
    expect.objectContaining({ method: "POST" }),
  ));
  const call = vi.mocked(fetch).mock.calls.find(
    ([url]) => typeof url === "string" && url.includes("/schedule"),
  );
  const body = call?.[1]?.body;
  const sent = JSON.parse(typeof body === "string" ? body : "{}") as Record<string, unknown>;
  expect(sent).toMatchObject({ change_id: "world_files", plan_id: "abc123def456", only_when_empty: true });
  expect(await screen.findByText(booking.detail)).toBeVisible();
});

test("a stale plan is answered with the fresh review rather than a dead end", async () => {
  const fresh: MaintenancePlan = {
    ...readyPlan,
    plan_id: "ffff0000ffff0000",
    headline: "Edit or replace world files is possible on Homestead, with things to know",
    protection: { ...readyPlan.protection, verified: true, backup_id: "backup-9" },
  };
  renderPanel({
    scheduleResponse: () => respond(
      { error: { code: "stale_plan", message: "This server has changed since you reviewed that plan." }, plan: fresh },
      409,
    ),
  });
  await reviewWorldFiles();
  fireEvent.click(await screen.findByRole("button", { name: "Schedule this plan" }));

  expect(await screen.findByText(/This server has changed since you reviewed that plan/)).toBeVisible();
  // The fresh review replaces the stale one in place, so the owner can just re-book.
  expect(await screen.findByText(/re-checked this backup against its manifest/)).toBeVisible();
  expect(screen.getByText(/plan ffff0000ffff0000/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Schedule this plan" })).toBeVisible();
});

test("nothing to change is not presented as a safety problem", async () => {
  const nothingToDo: MaintenancePlan = {
    ...readyPlan,
    change: catalog.changes[1],
    readiness: "not_applicable",
    headline: "There is nothing to change on Homestead",
    detail: "Homestead is already on the newest published release. This is not a problem to fix.",
    blockers: [],
  };
  renderPanel({ plan: nothingToDo, review: currentReview });
  fireEvent.click(await screen.findByRole("radio", { name: /Upgrade the server or loader version/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run the preflight" }));

  expect(await screen.findByText("Nothing to change")).toBeVisible();
  expect(screen.queryByText("Resolve this first")).toBeNull();
  expect(screen.queryByRole("list", { name: "Reviewed plan" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Schedule this plan" })).toBeNull();
});
