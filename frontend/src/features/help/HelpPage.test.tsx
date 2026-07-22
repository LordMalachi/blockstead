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

test("links to the only server even when it is stopped", () => {
  renderHelp(false);

  const backupGuide = screen.getByRole("heading", { name: "Protect, save, and restore a world" }).closest("article");
  expect(backupGuide).not.toBeNull();
  expect(backupGuide!.querySelector("a")).toHaveTextContent("Open Backup Center");
  expect(backupGuide!.querySelector("a")).toHaveAttribute("href", "/servers/profile-1/backups");
});

test("searches common synonyms and clears an empty result", () => {
  renderHelp();
  const search = screen.getByRole("searchbox", { name: "Search help" });

  fireEvent.change(search, { target: { value: "whitelist" } });
  expect(screen.getByRole("heading", { name: "Manage players" })).toBeVisible();

  fireEvent.change(search, { target: { value: "backup drive" } });
  expect(screen.getByRole("heading", { name: "Protect, save, and restore a world" })).toBeVisible();

  fireEvent.change(search, { target: { value: "forgot password" } });
  const resetLink = screen.getByRole("link", { name: /Open reset instructions/ });
  expect(resetLink.getAttribute("href")).toMatch(/#password-recovery$/);
  fireEvent.click(resetLink);
  expect(document.querySelector("#password-recovery")).toHaveAttribute("open");

  fireEvent.change(search, { target: { value: "notification report" } });
  const activityGuide = screen.getByRole("heading", { name: "Understand activity, alerts, and support reports" }).closest("article");
  expect(activityGuide).not.toBeNull();
  expect(activityGuide!.querySelector("a")).toHaveTextContent("Open Activity");
  expect(activityGuide!.querySelector("a")).toHaveAttribute("href", "/activity");

  fireEvent.change(search, { target: { value: "update" } });
  const updateGuide = screen.getByRole("heading", { name: "Update Blockstead" }).closest("article");
  expect(updateGuide).not.toBeNull();
  expect(updateGuide!.querySelector("a")).toHaveAttribute("href", "/system#updates");

  fireEvent.change(search, { target: { value: "something impossible" } });
  expect(screen.getByRole("link", { name: /Open Activity/ })).toHaveAttribute("href", "/activity");
  expect(screen.getByRole("link", { name: /Open diagnostics/ })).toHaveAttribute("href", "/system");
  fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
  expect(search).toHaveValue("");
  expect(screen.getByRole("heading", { name: "Help friends join" })).toBeVisible();
});

test("offers focused recovery paths when a crash search has no task match", () => {
  renderHelp();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search help" }), { target: { value: "crashed suddenly" } });

  expect(screen.getByRole("link", { name: /Open Activity/ })).toHaveTextContent("Find the failed event");
  expect(screen.getByRole("link", { name: /Open diagnostics/ })).toHaveTextContent("Check Java, disk space");
});
