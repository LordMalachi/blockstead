import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { SettingEntry, SettingsApplyResult, SettingsPreview, SettingsView } from "../../api/client";
import { SettingsPanel } from "./SettingsPanel";

const entries: SettingEntry[] = [
  { key: "difficulty", label: "Difficulty", category: "Gameplay", description: "Controls survival difficulty.", type: "string", value: "normal", minimum: null, maximum: null, options: ["peaceful", "easy", "normal", "hard"], restart_required: true },
  { key: "pvp", label: "Player-versus-player combat", category: "Gameplay", description: "Allows players to damage each other.", type: "boolean", value: true, minimum: null, maximum: null, options: [], restart_required: true },
  { key: "motd", label: "Server list message", category: "Players", description: "Message shown in Minecraft.", type: "string", value: "Home server", minimum: null, maximum: null, options: [], restart_required: true },
  { key: "max-players", label: "Player limit", category: "Players", description: "Maximum simultaneous players.", type: "integer", value: 20, minimum: 1, maximum: 1000, options: [], restart_required: true },
  { key: "server-port", label: "Server port", category: "Network", description: "Port players use to join.", type: "integer", value: 25565, minimum: 1, maximum: 65535, options: [], restart_required: true },
];
const view: SettingsView = { present: true, revision: "a".repeat(64), settings: entries, other_keys: ["custom-key"] };
const preview: SettingsPreview = { revision: view.revision!, restart_required: true, changes: [{ key: "max-players", label: "Player limit", category: "Players", before: 20, after: 30, restart_required: true }] };
const appliedView: SettingsView = { ...view, revision: "b".repeat(64), settings: entries.map(entry => entry.key === "max-players" ? { ...entry, value: 30 } : entry) };
const applied: SettingsApplyResult = { ...preview, previous_revision: view.revision!, revision: appliedView.revision!, snapshot_name: "snapshot.properties", view: appliedView };

function response(body: object) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPanel(fetchMock = vi.fn().mockResolvedValue(response(view))) {
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { fetchMock, ...render(<QueryClientProvider client={client}><SettingsPanel profileId="profile-1" running /></QueryClientProvider>) };
}

test("groups, describes, and searches guided settings", async () => {
  renderPanel();

  expect(await screen.findByRole("heading", { name: "Gameplay" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Players" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Network" })).toBeVisible();
  expect(screen.getByLabelText("Difficulty")).toHaveValue("normal");
  expect(screen.getByLabelText("Player-versus-player combat")).toBeChecked();
  expect(screen.getByText("Preserved advanced keys: custom-key.")).toBeVisible();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search settings" }), { target: { value: "port" } });
  expect(screen.getByLabelText("Server port")).toBeVisible();
  expect(screen.queryByLabelText("Difficulty")).not.toBeInTheDocument();
});

test("previews a typed diff and applies it with a recovery snapshot", async () => {
  const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") return response(preview);
    if (init?.method === "PUT") return response(applied);
    return response(view);
  });
  renderPanel(fetchMock);
  fireEvent.change(await screen.findByLabelText("Player limit"), { target: { value: "30" } });

  fireEvent.click(screen.getByRole("button", { name: "Review changes" }));

  expect(await screen.findByRole("heading", { name: "Review before saving" })).toBeVisible();
  expect(screen.getByText("20", { selector: "del" })).toBeVisible();
  expect(screen.getByText("30", { selector: "ins" })).toBeVisible();
  expect(screen.getByText(/take effect after the server restarts/i)).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Apply changes" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Recovery snapshot snapshot.properties");
  expect(screen.getByRole("status")).toHaveTextContent("Restart the server");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/settings",
    expect.objectContaining({ method: "PUT" }),
  ));
});
