import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { BackupPolicy, BackupRecord, RestorePreview, RestoreResult } from "../../api/client";
import { BackupsPanel } from "./BackupsPanel";

const completed: BackupRecord = {
  id: "backup-1",
  profile_id: "profile-1",
  status: "completed",
  method: "world_archive",
  trigger: "manual",
  file_name: "world.tar.gz",
  size_bytes: 2048,
  duration_ms: 1500,
  sha256: "a".repeat(64),
  included_paths: ["world"],
  archive_available: true,
  result: "Protected world.",
  created_at: "2026-07-17T14:30:00Z",
  completed_at: "2026-07-17T14:30:01.5Z",
};

const defaultPolicy: BackupPolicy = { keep_count: 10, keep_days: null, max_total_mb: null, redundancy_enabled: false, destinations: [] };

const verifiedPreview: RestorePreview = {
  backup_id: "backup-1",
  verified: true,
  sha256: completed.sha256 ?? "",
  size_bytes: 2048,
  included_paths: ["world"],
  worlds_replaced: ["world"],
  required_bytes: 70_000_000,
  available_bytes: 900_000_000,
  backup_created_at: "2026-07-17T14:30:00Z",
  minecraft_version: "1.21.9",
  can_restore: true,
  blockers: [],
};

const restoreResult: RestoreResult = {
  restored_paths: ["world"],
  preserved_paths: ["world.pre-restore-20260717-143000"],
  result: "Restored world.",
};

interface Handlers {
  records?: BackupRecord[];
  policy?: BackupPolicy;
  preview?: RestorePreview;
  running?: boolean;
}

function respond(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPanel({ records = [completed], policy = defaultPolicy, preview = verifiedPreview, running = false }: Handlers = {}) {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url.endsWith("/backup-policy") && method === "GET") return Promise.resolve(respond(policy));
    if (url.endsWith("/backup-policy") && method === "PUT") return Promise.resolve(respond({ ...policy, expired_now: 1 }));
    if (url.endsWith("/restore-preview")) return Promise.resolve(respond(preview));
    if (url.endsWith("/restore") && method === "POST") return Promise.resolve(respond(restoreResult));
    if (url.endsWith("/backups") && method === "POST") return Promise.resolve(respond(completed));
    return Promise.resolve(respond(records));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><BackupsPanel profileId="profile-1" running={running} /></QueryClientProvider>);
}

test("shows persisted backup history", async () => {
  renderPanel();

  expect(await screen.findByText("Protected world.")).toBeVisible();
  expect(screen.getByText("2.0 KB")).toBeVisible();
  expect(screen.getByText("1.5 s")).toBeVisible();
  expect(screen.getByRole("button", { name: "Choose folder & back up" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Restore…" })).toBeEnabled();
});

test("explains live save handling and starts a manual backup", async () => {
  renderPanel({ records: [], running: true });
  expect(await screen.findByText(/briefly pause saving/i)).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Choose folder & back up" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/api/v1/profiles/profile-1/backups",
      expect.objectContaining({ method: "POST" }),
    ));
});

test("reviews a verified restore before performing it", async () => {
  renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: "Restore…" }));

  expect(await screen.findByText(/passed checksum verification/i)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Restore this backup" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/backups/backup-1/restore",
    expect.objectContaining({ method: "POST" }),
  ));
  expect(await screen.findByText(/Restored world\./)).toBeVisible();
  expect(screen.getByText(/world\.pre-restore-20260717-143000/)).toBeVisible();
});

test("keeps restore disabled while a blocker exists", async () => {
  renderPanel({ preview: { ...verifiedPreview, can_restore: false, blockers: ["Stop this server before restoring a backup."] } });
  fireEvent.click(await screen.findByRole("button", { name: "Restore…" }));

  expect(await screen.findByText("Stop this server before restoring a backup.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Restore this backup" })).toBeDisabled();
});

test("expired backups cannot be restored from history", async () => {
  renderPanel({ records: [{ ...completed, status: "expired", archive_available: false, result: "Protected world. Removed by the retention policy." }] });

  expect(await screen.findByText(/Removed by the retention policy/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Restore…" })).toBeNull();
});

test("saves retention rules with blank meaning no limit", async () => {
  renderPanel();
  const count = await screen.findByLabelText(/Keep at most/);
  fireEvent.change(count, { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Save retention" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/backup-policy",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ keep_count: 3, keep_days: null, max_total_mb: null, redundancy_enabled: false, destinations: [] }),
    }),
  ));
  expect(await screen.findByText(/1 older backup removed/)).toBeVisible();
});

test("saves approved redundant backup destinations", async () => {
  renderPanel();
  fireEvent.click(await screen.findByText("Advanced redundant copies"));
  fireEvent.click(screen.getByLabelText(/Mirror every backup/));
  fireEvent.change(screen.getByLabelText("Destination folder"), {
    target: { value: "/media/backup-drive/minecraft" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add folder" }));
  fireEvent.click(screen.getByRole("button", { name: "Save backup settings" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/backup-policy",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({
        keep_count: 10,
        keep_days: null,
        max_total_mb: null,
        redundancy_enabled: true,
        destinations: ["/media/backup-drive/minecraft"],
      }),
    }),
  ));
});
