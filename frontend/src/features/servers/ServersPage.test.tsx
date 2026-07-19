import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
