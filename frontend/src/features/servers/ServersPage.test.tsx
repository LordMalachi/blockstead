import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
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
  const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const body = url.endsWith("/server/state")
      ? { state: "STOPPED", pid: null, exit_code: null, reason: "No server is running." }
      : url.endsWith("/profiles")
        ? [{ id: "server-1", name: "Family", server_directory: "/srv/minecraft/family", distribution: "vanilla", minecraft_version: "1.21.1", loader_version: null, is_fixture: false }]
        : url.endsWith("/schedules")
          ? []
          : url.endsWith("/players")
            ? { allowlist: { readable: false, players: [] } }
            : url.endsWith("/profiles/server-1") && init?.method === "DELETE"
              ? { id: "server-1", name: "Family", files_deleted: true, detail: "The profile, server folder, and Blockstead's local backups were deleted." }
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
  expect(within(dialog).getByRole("button", { name: "Remove from Blockstead" })).toBeDisabled();
  await user.click(within(dialog).getByRole("checkbox"));
  await user.type(within(dialog).getByLabelText(/Type Family to confirm/), "Family");
  await user.click(within(dialog).getByRole("button", { name: "Permanently delete server" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/server-1",
    expect.objectContaining({ method: "DELETE", body: JSON.stringify({ confirm_name: "Family", delete_files: true }) }),
  ));
});
