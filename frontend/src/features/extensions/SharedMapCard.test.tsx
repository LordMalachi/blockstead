import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import type { ExtensionEntry } from "../../api/client";
import { SharedMapCard } from "./SharedMapCard";

const squaremap: ExtensionEntry = {
  file_name: "squaremap-paper-mc1.21.11-1.3.14.jar",
  size_bytes: 1024,
  sha256: "abc",
  kind: "paper-plugin",
  loaders: ["paper"],
  identifier: "squaremap",
  display_name: "squaremap",
  version: "1.3.14",
  minecraft_constraint: "1.21",
  environment: null,
  dependencies: [],
  readable: true,
};

test("offers a one-click shared map install while the server is stopped", () => {
  const install = vi.fn();
  render(<SharedMapCard entries={[]} disabledEntries={[]} stopped busy={false} install={install} />);

  fireEvent.click(screen.getByRole("button", { name: "Install shared map" }));

  expect(install).toHaveBeenCalledOnce();
  expect(screen.getByText(/do not need to install a client mod/i)).toBeVisible();
});

test("locks installation while the server is active", () => {
  render(<SharedMapCard entries={[]} disabledEntries={[]} stopped={false} busy={false} install={vi.fn()} />);

  expect(screen.getByRole("button", { name: "Install shared map" })).toBeDisabled();
  expect(screen.getByText("Stop the server before installing the map.")).toBeVisible();
});

test("shows the default browser map link once squaremap is installed", () => {
  render(<SharedMapCard entries={[squaremap]} disabledEntries={[]} stopped={false} busy={false} install={vi.fn()} />);

  expect(screen.getByText("Installed")).toBeVisible();
  expect(screen.getByRole("link", { name: "Open default map address" })).toHaveAttribute("href", "http://localhost:8080");
  expect(screen.queryByRole("button", { name: "Install shared map" })).not.toBeInTheDocument();
});

test("does not offer to reinstall a disabled squaremap jar", () => {
  render(<SharedMapCard entries={[]} disabledEntries={[squaremap]} stopped busy={false} install={vi.fn()} />);

  expect(screen.getByText("Installed but disabled")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Install shared map" })).not.toBeInTheDocument();
});
