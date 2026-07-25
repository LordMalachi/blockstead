import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { MaintenanceCatalog, MaintenancePlan } from "../../api/client";
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

function respond(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPanel(plan: MaintenancePlan = readyPlan) {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.includes("/maintenance/preflight")) return Promise.resolve(respond(plan));
    return Promise.resolve(respond(catalog));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><MaintenancePanel profileId="profile-1" /></MemoryRouter>
    </QueryClientProvider>,
  );
}

test("lists the reviewable changes and states which need a stopped server", async () => {
  renderPanel();
  expect(await screen.findByText("Edit or replace world files")).toBeVisible();
  expect(screen.getAllByText(/Stopped server only/)).toHaveLength(2);
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
  renderPanel(blockedPlan);
  fireEvent.click(await screen.findByRole("radio", { name: /Upgrade the server or loader version/ }));
  fireEvent.click(screen.getByRole("button", { name: "Run the preflight" }));

  expect(await screen.findByText("Resolve this first")).toBeVisible();
  expect(screen.queryByRole("list", { name: "Reviewed plan" })).toBeNull();
  expect(screen.getByText("Blockstead has no verified upgrade source for Fabric.")).toBeVisible();
});
