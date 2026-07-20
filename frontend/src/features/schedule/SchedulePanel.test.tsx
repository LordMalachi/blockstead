import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { Schedule } from "../../api/client";
import { SchedulePanel } from "./SchedulePanel";

const schedule: Schedule = {
  id: "schedule-1",
  profile_id: "profile-1",
  enabled: true,
  start_time: "09:00",
  stop_time: "22:00",
  backup_before_stop: true,
  power_off_after_stop: false,
  wake_time: null,
  weekdays: [0, 1, 2, 3, 4],
  only_when_empty: false,
  power_capable: false,
  maintenance_steps: ["Announce maintenance", "Flush Minecraft saves", "Create a verified backup", "Stop the server safely"],
  next_executions: [{ kind: "recurring", action: "start", label: "Start server", at: "2099-07-20T09:00:00-05:00", steps: ["Start the server"] }],
  one_time_events: [],
  history: [{ id: "run-1", trigger: "scheduled", action: "maintenance", status: "success", steps: ["Stop the server safely"], detail: "Completed maintenance for Home.", duration_ms: 840, started_at: "2026-07-19T22:00:00Z", completed_at: "2026-07-19T22:00:00Z" }],
};

function response(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPanel() {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith("/automation/capabilities")) return Promise.resolve(response({ host_power: false }));
    if (url.endsWith("/schedules") && !init?.method) return Promise.resolve(response([schedule]));
    if (url.endsWith("/run")) return Promise.resolve(response(schedule.history[0]));
    return Promise.resolve(response(schedule));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><SchedulePanel profileId="profile-1" /></QueryClientProvider>);
}

test("shows the ordered preview, upcoming work, and execution history", async () => {
  renderPanel();

  expect(await screen.findByText("What Blockstead will do")).toBeVisible();
  expect(screen.getByText("Create a verified backup")).toBeVisible();
  expect(screen.getByText("Next three executions")).toBeVisible();
  expect(await screen.findByText("Completed maintenance for Home.")).toBeVisible();
  expect(screen.getByRole("checkbox", { name: /shut down the computer/i })).toBeDisabled();
});

test("applies a preset and saves weekday-aware settings", async () => {
  renderPanel();
  await screen.findByDisplayValue("09:00");
  fireEvent.click(screen.getByRole("button", { name: "Weekend only" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Stop only when nobody is online" }));
  fireEvent.click(screen.getByRole("button", { name: "Save plan" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/schedules/profile-1",
    expect.objectContaining({ method: "PUT" }),
  ));
  const put = vi.mocked(fetch).mock.calls.find(([url, init]) => url === "/api/v1/schedules/profile-1" && init?.method === "PUT");
  const body = put?.[1]?.body;
  expect(typeof body).toBe("string");
  if (typeof body !== "string") throw new Error("Expected a JSON request body.");
  expect(body).toContain('"weekdays":[5,6]');
  expect(screen.getByRole("checkbox", { name: "Sat" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Sun" })).toBeChecked();
});
