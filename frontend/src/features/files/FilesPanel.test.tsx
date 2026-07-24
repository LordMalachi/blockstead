import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import type {
  FileContent,
  FileDeleteResult,
  FileEditPreview,
  FileEditResult,
  FileListing,
  FileRenameResult,
} from "../../api/client";
import { FilesPanel } from "./FilesPanel";

const configListing: FileListing = {
  category: "config",
  path: "",
  writable: true,
  stopped_required: false,
  entries: [
    {
      name: "server.properties",
      path: "server.properties",
      is_dir: false,
      size_bytes: 42,
      modified_at: "2026-07-20T10:00:00Z",
      viewable: true,
      editable: true,
    },
  ],
};

const worldListing: FileListing = {
  category: "world",
  path: "",
  writable: true,
  stopped_required: true,
  entries: [
    { name: "world", path: "world", is_dir: true, size_bytes: null, modified_at: null, viewable: false, editable: false },
  ],
};

const backupsListing: FileListing = {
  category: "backups",
  path: "",
  writable: false,
  stopped_required: false,
  entries: [
    {
      name: "20260720-140000-abcd1234.tar.gz",
      path: "20260720-140000-abcd1234.tar.gz",
      is_dir: false,
      size_bytes: 2048,
      modified_at: "2026-07-20T14:00:00Z",
      viewable: false,
      editable: false,
    },
  ],
};

const fileContent: FileContent = {
  path: "server.properties",
  content: "motd=Hi\n",
  revision: "a".repeat(64),
  editable: true,
};

const editPreview: FileEditPreview = { revision: "a".repeat(64), valid: true, problems: [], no_changes: false };
const editResult: FileEditResult = {
  path: "server.properties",
  snapshot_name: "20260722-120000-aa11bb22-server.properties",
  previous_revision: "a".repeat(64),
  revision: "b".repeat(64),
};
const renameResult: FileRenameResult = { path: "server.properties.bak" };
const deleteResult: FileDeleteResult = { snapshot_name: "20260722-120000-cc33dd44-server.properties", preserved_name: null };

function respond(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderPanel({ stopped = true }: { stopped?: boolean } = {}) {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url.includes("/files/config/content/preview")) return Promise.resolve(respond(editPreview));
    if (url.includes("/files/config/content") && method === "PUT") return Promise.resolve(respond(editResult));
    if (url.includes("/files/config/content")) return Promise.resolve(respond(fileContent));
    if (url.includes("/files/config/rename")) return Promise.resolve(respond(renameResult));
    if (url.includes("/files/config") && method === "DELETE") return Promise.resolve(respond(deleteResult));
    if (url.includes("/files/config")) return Promise.resolve(respond(configListing));
    if (url.includes("/files/world")) return Promise.resolve(respond(worldListing));
    if (url.includes("/files/backups")) return Promise.resolve(respond(backupsListing));
    if (url.includes("/files/logs") || url.includes("/files/extensions")) {
      return Promise.resolve(respond({ ...configListing, category: "logs", entries: [] }));
    }
    return Promise.resolve(respond(configListing));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><FilesPanel profileId="profile-1" distribution="fabric" stopped={stopped} /></QueryClientProvider>);
}

test("lists entries for the default config category", async () => {
  renderPanel();
  expect(await screen.findByText("server.properties")).toBeVisible();
  expect(screen.getByRole("button", { name: "Config" })).toHaveAttribute("aria-pressed", "true");
});

test("switching category reloads the listing for that category", async () => {
  renderPanel();
  await screen.findByText("server.properties");

  fireEvent.click(screen.getByRole("button", { name: "Backups" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/files/backups"),
    expect.anything(),
  ));
  expect(await screen.findByText("20260720-140000-abcd1234.tar.gz")).toBeVisible();
});

test("opens a file, checks changes, and saves with a recovery snapshot", async () => {
  renderPanel();
  fireEvent.click(await screen.findByRole("button", { name: /server\.properties/ }));

  const textarea = await screen.findByLabelText("Content of server.properties");
  fireEvent.change(textarea, { target: { value: "motd=Bye\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Check changes" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/files/config/content/preview",
    expect.objectContaining({ method: "POST" }),
  ));
  const save = await screen.findByRole("button", { name: "Save file" });
  await waitFor(() => expect(save).toBeEnabled());
  fireEvent.click(save);

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/files/config/content",
    expect.objectContaining({ method: "PUT" }),
  ));
  expect(await screen.findByText(/Recovery snapshot 20260722-120000-aa11bb22-server\.properties/)).toBeVisible();
});

test("renames an entry", async () => {
  renderPanel();
  await screen.findByText("server.properties");

  fireEvent.click(screen.getByRole("button", { name: "Rename" }));
  const input = screen.getByLabelText("New name for server.properties");
  fireEvent.change(input, { target: { value: "server.properties.bak" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/files/config/rename",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ path: "server.properties", new_name: "server.properties.bak" }),
    }),
  ));
});

test("deletes an entry only after a second confirming click", async () => {
  renderPanel();
  await screen.findByText("server.properties");

  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  const confirm = screen.getByRole("button", { name: "Confirm delete" });
  expect(fetch).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ method: "DELETE" }));

  fireEvent.click(confirm);

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/files/config?path=server.properties",
    expect.objectContaining({ method: "DELETE" }),
  ));
  expect(await screen.findByText(/Recovery snapshot 20260722-120000-cc33dd44-server\.properties/)).toBeVisible();
});

test("hides mutation controls for a read-only category", async () => {
  renderPanel();
  await screen.findByText("server.properties");

  fireEvent.click(screen.getByRole("button", { name: "Backups" }));
  await screen.findByText("20260720-140000-abcd1234.tar.gz");

  expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Upload into this folder" })).not.toBeInTheDocument();
});

test("warns and locks mutations when a stopped server is required", async () => {
  renderPanel({ stopped: false });
  await screen.findByText("server.properties");

  fireEvent.click(screen.getByRole("button", { name: "World" }));

  expect(await screen.findByText(/Stop the server before uploading, renaming, deleting, or extracting/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
});
