import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { LoaderMigrationPanel } from "./LoaderMigrationPanel";

const review = {
  review_id: "1234567890abcdef",
  profile_id: "profile-1",
  source_distribution: "fabric",
  target_distribution: "paper",
  minecraft_version: "1.21.1",
  loader_version: null,
  level_name: "family",
  worlds: ["family", "family_nether", "family_the_end"],
  world_size_bytes: 4096,
  disk_free_bytes: 1_000_000_000,
  required_java_major: 21,
  java_ready: true,
  stopped: true,
  protection: { verified: true, backup_id: "backup-1", age_hours: 1, detail: "Fresh verified backup." },
  extensions: [{
    file_name: "fabric-mod.jar",
    name: "Fabric Mod",
    version: "1.0",
    identifier: "fabric-mod",
    source_kind: "fabric-mod",
    classification: "replacement_needed",
    detail: "Find a Paper replacement.",
  }],
  modded_world_warning: true,
  blockers: [],
  ready: true,
};

test("reviews and creates a protected loader copy", async () => {
  const fetch = vi.fn().mockImplementation((url: string) => {
    const body = url.endsWith("/profiles")
      ? [{ id: "profile-1", name: "Family", server_directory: "/servers/family", distribution: "fabric", minecraft_version: "1.21.1", loader_version: "1", is_fixture: false }]
      : url.includes("/loader-migration/review")
        ? review
        : { id: "profile-2", name: "Family · Paper", distribution: "paper", minecraft_version: "1.21.1", loader_version: null, worlds_copied: review.worlds, source_profile_id: "profile-1", source_unchanged: true, extensions: review.extensions, next_route: "/servers/profile-2/mods?migration=1", eula_accepted: false };
    return Promise.resolve(new Response(JSON.stringify(body), { status: url.includes("/apply") ? 201 : 200, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><LoaderMigrationPanel profileId="profile-1" /></MemoryRouter>
    </QueryClientProvider>,
  );

  fireEvent.click(screen.getByRole("button", { name: "Review modded copy" }));
  expect(await screen.findByText("Extension rebuild checklist")).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Create Paper copy" }));

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/loader-migration/apply",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        target_distribution: "paper",
        review_id: review.review_id,
        backup_id: "backup-1",
        loader_version: null,
        name: "Family · Paper",
        directory_name: "family-paper",
        acknowledge_modded_world: true,
      }),
    }),
  ));
});
