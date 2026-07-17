import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type { RawSettingsApplyResult, RawSettingsPreview, RawSettingsView, SettingEntry, SettingsApplyResult, SettingsPreview, SettingsView } from "../../api/client";
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

const RAW_CONTENT = "# family server\nmotd=Home server\nrcon.password=••••••••\n";
const RAW_REVISION = "c".repeat(64);
const rawView: RawSettingsView = {
  present: true,
  editable: true,
  problem: null,
  revision: RAW_REVISION,
  content: RAW_CONTENT,
  secret_keys: ["rcon.password"],
};
const rawValid: RawSettingsPreview = {
  revision: RAW_REVISION,
  valid: true,
  problems: [],
  no_changes: false,
  changed_known: [{ key: "motd", label: "Server list message", category: "Players", before: "Home server", after: "Neighbors welcome", restart_required: true }],
  removed_known: [],
  other_lines_changed: false,
  restart_required: true,
};
const rawApplied: RawSettingsApplyResult = {
  snapshot_name: "raw-snapshot.properties",
  previous_revision: RAW_REVISION,
  revision: "d".repeat(64),
  changed_known: rawValid.changed_known,
  removed_known: [],
  other_lines_changed: false,
  restart_required: true,
  view: appliedView,
};

function rawFetchMock(preview: RawSettingsPreview) {
  return vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/settings/raw/preview")) return response(preview);
    if (url.endsWith("/settings/raw") && init?.method === "PUT") return response(rawApplied);
    if (url.endsWith("/settings/raw")) return response(rawView);
    return response(view);
  });
}

test("raw editor hides secrets, validates, and saves with a recovery copy", async () => {
  const fetchMock = rawFetchMock(rawValid);
  renderPanel(fetchMock);

  fireEvent.click(await screen.findByRole("button", { name: "Open raw editor" }));
  const editor = await screen.findByLabelText("server.properties content");
  expect(editor).toHaveValue(RAW_CONTENT);
  expect(screen.getByText(/appear as •••••••• and stay unchanged/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Save file" })).toBeDisabled();

  fireEvent.change(editor, { target: { value: RAW_CONTENT.replace("Home server", "Neighbors welcome") } });
  fireEvent.click(screen.getByRole("button", { name: "Check changes" }));

  expect(await screen.findByText(/Checks passed/)).toBeVisible();
  expect(screen.getByText(/Changes Server list message/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Save file" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/settings/raw",
    expect.objectContaining({ method: "PUT" }),
  ));
  expect(await screen.findByText(/Recovery snapshot raw-snapshot\.properties/)).toBeVisible();
});

test("raw editor lists validation problems and blocks saving", async () => {
  const invalid: RawSettingsPreview = { ...rawValid, valid: false, problems: ["Line 2: Player limit must be at least 1."], changed_known: [] };
  renderPanel(rawFetchMock(invalid));

  fireEvent.click(await screen.findByRole("button", { name: "Open raw editor" }));
  const editor = await screen.findByLabelText("server.properties content");
  fireEvent.change(editor, { target: { value: "max-players=-5\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Check changes" }));

  expect(await screen.findByText("Line 2: Player limit must be at least 1.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Save file" })).toBeDisabled();
});
