import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { BackupRecord } from "../../api/client";
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
  result: "Protected world.",
  created_at: "2026-07-17T14:30:00Z",
  completed_at: "2026-07-17T14:30:01.5Z",
};

function renderPanel(records: BackupRecord[] = [completed], running = false) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(records), { status: 200, headers: { "Content-Type": "application/json" } })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><BackupsPanel profileId="profile-1" running={running} /></QueryClientProvider>);
}

test("shows persisted backup history", async () => {
  renderPanel();

  expect(await screen.findByText("Protected world.")).toBeVisible();
  expect(screen.getByText("2.0 KB")).toBeVisible();
  expect(screen.getByText("1.5 s")).toBeVisible();
  expect(screen.getByRole("button", { name: "Back up now" })).toBeEnabled();
});

test("explains live save handling and starts a manual backup", async () => {
  renderPanel([], true);
  expect(await screen.findByText(/briefly pause saving/i)).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Back up now" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/api/v1/profiles/profile-1/backups",
      expect.objectContaining({ method: "POST" }),
    ));
});
