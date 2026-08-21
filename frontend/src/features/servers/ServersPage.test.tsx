import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { SERVER_DIRECTORY_PATTERN } from "../../lib/server-directory";
import { ServersPage } from "./ServersPage";

test("shows one guided setup workflow at a time for the first server", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = url.endsWith("/server/state")
      ? { state: "STOPPED", pid: null, exit_code: null, reason: "No server is running." }
      : url.endsWith("/profiles") || url.endsWith("/schedules")
        ? []
        : url.includes("/provision/versions/")
          ? { distribution: "vanilla", versions: ["1.21.1"] }
          : {};
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
  }));

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><ServersPage /></QueryClientProvider></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "Create a configured profile" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Import a server folder" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Modpacks" })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /Use an existing server/ }));
  expect(screen.getByRole("heading", { name: "Import a server folder" })).toBeVisible();
  expect(screen.getByLabelText("Profile name")).toHaveValue("My Server");
  expect(screen.getByLabelText("Server folder")).toHaveAttribute("webkitdirectory");
  expect(screen.getByRole("button", { name: "Copy folder in" })).toBeDisabled();
  expect(screen.getByPlaceholderText("/srv/minecraft/my-server")).toBeRequired();
  expect(screen.queryByRole("heading", { name: "Create a configured profile" })).not.toBeInTheDocument();
});

test("requires a clear confirmation before removing a server", async () => {
  let deleted = false;
  const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/profiles/server-1") && init?.method === "DELETE") deleted = true;
    const body = url.endsWith("/server/state")
      ? { state: "STOPPED", pid: null, exit_code: null, reason: "No server is running." }
      : url.endsWith("/profiles")
        ? deleted ? [] : [{ id: "server-1", name: "Family", server_directory: "/srv/minecraft/family", distribution: "vanilla", minecraft_version: "1.21.1", loader_version: null, is_fixture: false }]
        : url.endsWith("/schedules")
          ? []
          : url.endsWith("/players")
            ? { allowlist: { readable: false, players: [] } }
            : url.endsWith("/profiles/server-1/removal-review")
              ? {
                  id: "server-1",
                  name: "Family",
                  server_directory: "/srv/minecraft/family",
                  worlds: [{ name: "world", path: "/srv/minecraft/family/world", size_bytes: 2048 }],
                  local_backup_directory: "/var/lib/blockstead/backups/server-1",
                  local_backups_present: true,
                  external_backup_directories: ["/mnt/safe/blockstead-backups/server-1"],
                  can_remove_record: true,
                  can_delete_files: true,
                  blockers: [],
                  delete_files_blockers: [],
                }
            : url.endsWith("/profiles/server-1") && init?.method === "DELETE"
              ? { id: "server-1", name: "Family", files_deleted: true, server_directory: "/srv/minecraft/family", local_backup_directory: "/var/lib/blockstead/backups/server-1", external_backup_directories: ["/mnt/safe/blockstead-backups/server-1"], detail: "Permanently deleted the server folder." }
              : url.includes("/provision/versions/")
                ? { distribution: "vanilla", versions: ["1.21.1"] }
                : {};
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><ServersPage /></QueryClientProvider></MemoryRouter>);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Remove server" }));
  const dialog = screen.getByRole("dialog", { name: /Review removal of “Family”/ });
  expect(dialog).toHaveTextContent("Nothing has changed yet");
  expect(await within(dialog).findByText("/srv/minecraft/family/world")).toBeVisible();
  expect(within(dialog).getByText("/var/lib/blockstead/backups/server-1")).toBeVisible();
  expect(within(dialog).getByText("/mnt/safe/blockstead-backups/server-1")).toBeVisible();
  expect(within(dialog).getByRole("button", { name: "Remove from Blockstead" })).toBeDisabled();
  await user.click(within(dialog).getByRole("checkbox"));
  await user.type(within(dialog).getByLabelText(/Type Family to confirm/), "Family");
  await user.click(within(dialog).getByRole("button", { name: "Permanently delete server and worlds" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/server-1",
    expect.objectContaining({ method: "DELETE", body: JSON.stringify({ confirm_name: "Family", delete_files: true }) }),
  ));
  await waitFor(() => expect(client.getQueryData(["profiles"])).toEqual([]));
  expect(screen.queryByRole("button", { name: "Remove server" })).not.toBeInTheDocument();
});

test("derives a folder name from the picked folder that already passes the pattern", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = url.endsWith("/server/state")
      ? { state: "STOPPED", pid: null, exit_code: null, reason: "No server is running." }
      : url.endsWith("/profiles") || url.endsWith("/schedules")
        ? []
        : url.includes("/provision/versions/")
          ? { distribution: "vanilla", versions: ["1.21.1"] }
          : {};
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><ServersPage /></QueryClientProvider></MemoryRouter>);
  await userEvent.click(await screen.findByRole("button", { name: /Use an existing server/ }));

  const folderInput = screen.getByLabelText<HTMLInputElement>("Server folder");
  const file = new File(["contents"], "server.properties");
  Object.defineProperty(file, "webkitRelativePath", { value: "My Server Files/server.properties" });
  fireEvent.change(folderInput, { target: { files: [file] } });

  const note = await screen.findByText(/Ready to copy/);
  expect(note).toHaveTextContent("my-server-files");
  expect(SERVER_DIRECTORY_PATTERN.test("my-server-files")).toBe(true);
  expect(folderInput).not.toHaveAttribute("aria-invalid");
});

test("highlights the folder control and applies the suggested name in one click when the derived folder is rejected", async () => {
  const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/imports/uploads") && init?.method === "POST") {
      return Promise.resolve(new Response(JSON.stringify({
        error: {
          code: "REQUEST_INVALID",
          message: "That folder name is not allowed.",
          recovery: "Review the highlighted fields and try again.",
          fields: [{ field: "directory_name", reason: "RESERVED_NAME", message: "That folder name is reserved by Blockstead.", rule: null, suggestion: "my-server-files-safe" }],
        },
      }), { status: 422, headers: { "Content-Type": "application/json" } }));
    }
    const body = url.endsWith("/server/state")
      ? { state: "STOPPED", pid: null, exit_code: null, reason: "No server is running." }
      : url.endsWith("/profiles") || url.endsWith("/schedules")
        ? []
        : url.includes("/provision/versions/")
          ? { distribution: "vanilla", versions: ["1.21.1"] }
          : {};
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetch);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}><ServersPage /></QueryClientProvider></MemoryRouter>);
  await userEvent.click(await screen.findByRole("button", { name: /Use an existing server/ }));

  const folderInput = screen.getByLabelText<HTMLInputElement>("Server folder");
  const file = new File(["contents"], "server.properties");
  Object.defineProperty(file, "webkitRelativePath", { value: "My Server Files/server.properties" });
  fireEvent.change(folderInput, { target: { files: [file] } });
  await userEvent.click(screen.getByRole("button", { name: "Copy folder in" }));

  await waitFor(() => expect(folderInput).toHaveAttribute("aria-invalid", "true"));
  expect(screen.getByText("That folder name is reserved by Blockstead.")).toBeVisible();

  await userEvent.click(screen.getByRole("button", { name: /Use suggested name.*my-server-files-safe/ }));
  expect(folderInput).not.toHaveAttribute("aria-invalid");
  expect(await screen.findByText(/Ready to copy/)).toHaveTextContent("my-server-files-safe");

  await userEvent.click(screen.getByRole("button", { name: "Copy folder in" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/imports/uploads",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ directory_name: "my-server-files-safe" }) }),
  ));
});
