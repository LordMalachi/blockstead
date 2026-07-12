import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { PrerequisitesPanel } from "./PrerequisitesPanel";
import type { PrerequisitesView } from "../../api/client";

const prerequisites: PrerequisitesView = {
  distribution: "fabric", label: "Fabric", minecraft_version: "1.21.1", is_fixture: false,
  eula_accepted: false, required_java_major: 21, java_runtimes: [], selected_java: null,
  java_satisfied: false, launch_files_ready: true, launch_problem: null,
  extension_directory: "mods", extension_directory_present: true,
};

test("makes Java and EULA setup actions visible", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(prerequisites), { status: 200, headers: { "Content-Type": "application/json" } })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><PrerequisitesPanel profileId="profile-1" /></QueryClientProvider>);
  expect(await screen.findByText("Java 21 needed")).toBeVisible();
  expect(screen.getByText("EULA not accepted")).toBeVisible();
  expect(screen.getByRole("button", { name: "Accept Minecraft EULA" })).toBeEnabled();
});
