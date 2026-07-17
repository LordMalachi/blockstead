import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { ProvisionPanel } from "./ProvisionPanel";

function renderPanel() {
  const fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/provision/versions/")) return Promise.resolve(new Response(JSON.stringify({ distribution: "vanilla", versions: ["1.21.1"] }), { status: 200, headers: { "Content-Type": "application/json" } }));
    return Promise.resolve(new Response(JSON.stringify({ id: "new-profile", name: "Family Server", distribution: "vanilla", minecraft_version: "1.21.1", loader_version: null, directory: "/srv/family-server", notes: [], eula_accepted: false }), { status: 201, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetch);
  const onCreated = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
