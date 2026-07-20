import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { HelpPage } from "./HelpPage";
import { WalkthroughProvider } from "./Walkthrough";

function renderHelp(activeProfile = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["profiles"], [{ id: "profile-1", name: "Family", server_directory: "/srv/minecraft/family", distribution: "paper", minecraft_version: "1.21.1", loader_version: null, is_fixture: false }]);
  client.setQueryData(["state"], { state: activeProfile ? "RUNNING" : "STOPPED", pid: activeProfile ? 1 : null, exit_code: null, reason: activeProfile ? "Ready" : "Stopped", profile_id: activeProfile ? "profile-1" : null });
  return render(<MemoryRouter><QueryClientProvider client={client}><WalkthroughProvider><HelpPage /></WalkthroughProvider></QueryClientProvider></MemoryRouter>);
}

test("searches the central task guides and links into the active server", () => {
  renderHelp();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search help" }), { target: { value: "backup" } });

  expect(screen.getByRole("heading", { name: "Protect, save, and restore a world" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Manage players" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Open Backup Center/ })).toHaveAttribute("href", "/servers/profile-1/backups");
});

test("starts the guided tour from Help", () => {
  renderHelp();

  fireEvent.click(screen.getByRole("button", { name: "Start guided tour" }));

  expect(screen.getByRole("dialog", { name: "A quick tour of Blockstead" })).toBeVisible();
});

test("asks the owner to choose a server when none is active", () => {
  renderHelp(false);

  const backupGuide = screen.getByRole("heading", { name: "Protect, save, and restore a world" }).closest("article");
  expect(backupGuide).not.toBeNull();
  expect(backupGuide!.querySelector("a")).toHaveTextContent("Choose a server");
  expect(backupGuide!.querySelector("a")).toHaveAttribute("href", "/servers");
});
