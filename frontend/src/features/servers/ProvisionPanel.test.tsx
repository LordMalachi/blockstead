import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { SERVER_DIRECTORY_PATTERN } from "../../lib/server-directory";
import { ProvisionPanel } from "./ProvisionPanel";

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderPanel(onProvision?: () => Response) {
  const fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/provision/versions/")) return Promise.resolve(respond({ distribution: "vanilla", versions: ["1.21.1"] }));
    if (onProvision) return Promise.resolve(onProvision());
    return Promise.resolve(respond({ id: "new-profile", name: "Family Server", distribution: "vanilla", minecraft_version: "1.21.1", loader_version: null, directory: "/srv/family-server", notes: [], eula_accepted: false }, 201));
  });
  vi.stubGlobal("fetch", fetch);
  const onCreated = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ProvisionPanel stopped onCreated={onCreated} /></QueryClientProvider>);
  return { fetch, onCreated };
}

test("offers every requested loader", async () => {
  renderPanel();
  const select = await screen.findByLabelText("Server type");
  expect(select).toHaveTextContent("Vanilla");
  expect(select).toHaveTextContent("Fabric");
  expect(select).toHaveTextContent("Forge");
  expect(select).toHaveTextContent("Quilt");
  expect(select).toHaveTextContent("NeoForge");
});

test("creates a profile from the selected official version", async () => {
  const user = userEvent.setup();
  const { fetch, onCreated } = renderPanel();
  expect(await screen.findByRole("option", { name: "1.21.1" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Create server" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new-profile"));
  expect(fetch).toHaveBeenCalledWith("/api/v1/provision", expect.objectContaining({ method: "POST" }));
});

test("pre-fills defaults that already satisfy the server folder pattern", async () => {
  renderPanel();
  await screen.findByRole("option", { name: "1.21.1" });
  const name = screen.getByLabelText<HTMLInputElement>("Profile name");
  const directory = screen.getByLabelText<HTMLInputElement>("Server folder");
  expect(name.value).toBe("Family Server");
  expect(directory.value).toBe("family-server");
  expect(SERVER_DIRECTORY_PATTERN.test(directory.value)).toBe(true);
  expect(directory).not.toHaveAttribute("aria-invalid");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("shows a live suggestion while typing an invalid folder name, before submit", async () => {
  renderPanel();
  await screen.findByRole("option", { name: "1.21.1" });
  const directory = screen.getByLabelText("Server folder");

  fireEvent.change(directory, { target: { value: "My__Server!!" } });

  expect(directory).toHaveAttribute("aria-invalid", "true");
  expect(directory).toHaveClass("field-invalid");
  const notice = screen.getByRole("alert");
  expect(notice).toHaveTextContent(/Use only lowercase letters/);
  expect(screen.getByRole("button", { name: /Use suggested name.*my_server/ })).toBeVisible();
});

test("clicking the suggestion fixes the folder name in one click", async () => {
  renderPanel();
  await screen.findByRole("option", { name: "1.21.1" });
  const directory = screen.getByLabelText("Server folder");
  fireEvent.change(directory, { target: { value: "My__Server!!" } });

  fireEvent.click(screen.getByRole("button", { name: /Use suggested name.*my_server/ }));

  expect(directory).toHaveValue("my_server");
  expect(directory).not.toHaveAttribute("aria-invalid");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("highlights the server folder control when the API reports a field error", async () => {
  const user = userEvent.setup();
  const { onCreated } = renderPanel(() => respond({
    error: {
      code: "REQUEST_INVALID",
      message: "Some submitted information was invalid.",
      recovery: "Review the highlighted fields and try again.",
      fields: [{
        field: "directory_name",
        reason: "ALREADY_EXISTS",
        message: "A server already uses this folder name.",
        rule: "Choose a folder name that isn't already in use.",
        suggestion: "family-server-2",
      }],
    },
  }, 422));
  await screen.findByRole("option", { name: "1.21.1" });

  await user.click(screen.getByRole("button", { name: "Create server" }));

  const directory = await screen.findByLabelText("Server folder");
  await waitFor(() => expect(directory).toHaveAttribute("aria-invalid", "true"));
  expect(screen.getByText("A server already uses this folder name.")).toBeVisible();
  expect(onCreated).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: /Use suggested name.*family-server-2/ }));
  expect(directory).toHaveValue("family-server-2");
});
