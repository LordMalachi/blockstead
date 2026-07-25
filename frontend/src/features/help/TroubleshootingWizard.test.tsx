import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";
import type {
  Profile,
  TroubleshootingAssessment,
  TroubleshootingCatalog,
} from "../../api/client";
import { TroubleshootingWizard } from "./TroubleshootingWizard";

const profile: Profile = {
  id: "profile-1",
  name: "Family",
  server_directory: "/srv/minecraft/family",
  distribution: "paper",
  minecraft_version: "1.21.1",
  loader_version: null,
  is_fixture: false,
};

const catalog: TroubleshootingCatalog = {
  version: "2026.07.1",
  problems: [
    {
      id: "player_cannot_join",
      title: "A specific player cannot join",
      summary: "Check access rules.",
      requires_player_name: true,
      checks: ["Selected server is running", "Player is on the allowlist"],
      possible_solutions: ["Add the player to the allowlist"],
      source_ids: ["paper-properties"],
    },
    {
      id: "public_connection",
      title: "Friends outside my network cannot join",
      summary: "Check local evidence and identify external checks.",
      requires_player_name: false,
      checks: ["Selected server is running", "External port is confirmed"],
      possible_solutions: ["Review router forwarding"],
      source_ids: ["minecraft-server-setup"],
    },
  ],
  sources: [
    {
      id: "paper-properties",
      title: "server.properties reference",
      url: "https://docs.papermc.io/paper/reference/server-properties/",
      publisher: "PaperMC",
      checked_at: "2026-07-23",
    },
    {
      id: "minecraft-server-setup",
      title: "How to Setup a Minecraft: Java Edition Server",
      url: "https://help.minecraft.net/hc/en-us/articles/360058525452-How-to-Setup-a-Minecraft-Java-Edition-Server",
      publisher: "Minecraft Help",
      checked_at: "2026-07-23",
    },
  ],
};

const assessment: TroubleshootingAssessment = {
  catalog_version: "2026.07.1",
  problem: catalog.problems[0],
  outcome: "problem_found",
  headline: "Blockstead found a confirmed problem",
  detail: "Review the evidence and repair.",
  checks: [
    {
      id: "server-running",
      label: "Selected server is running",
      status: "passed",
      certainty: "none",
      detail: "Family is running.",
      source_ids: [],
    },
    {
      id: "allowlist",
      label: "New_Player is on the allowlist",
      status: "flagged",
      certainty: "confirmed",
      detail: "The allowlist is enabled, but this player is not listed.",
      source_ids: ["paper-properties"],
    },
  ],
  actions: [
    {
      id: "allowlist_add",
      label: "Add New_Player to the allowlist",
      description: "Send Minecraft's supported allowlist command.",
      impact: "New_Player will be allowed to join Family.",
      confirmation: "Add New_Player to the allowlist for Family?",
      available: true,
      blockers: [],
      destructive: false,
    },
  ],
  next_steps: ["Continue with connection checks if access rules pass."],
  sources: [catalog.sources[0]],
};

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** What the stub actually needs: a URL and the init, answered synchronously. */
type FetchStub = (url: string, init?: RequestInit) => Response;

/** `fetch` accepts a string, a URL, or a Request; each carries its URL differently. */
function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
}

function renderWizard(handle: FetchStub) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve(handle(requestUrl(input), init)),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <TroubleshootingWizard profiles={[profile]} suggestedProfileId={profile.id} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("walks through a read-only check before showing a repair", async () => {
  renderWizard((url, init) => {
    if (url.endsWith("/troubleshooting/problems")) return respond(catalog);
    if (url.endsWith("/troubleshooting/assess") && init?.method === "POST") {
      return respond(assessment);
    }
    return respond({});
  });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("radio", { name: /A specific player cannot join/ }));
  await user.type(screen.getByLabelText("Minecraft player name"), "New_Player");
  expect(screen.getByText("Add the player to the allowlist")).toBeVisible();

  await user.click(screen.getByRole("button", { name: "Continue to checks" }));
  expect(screen.getByText(/will not stop, restart, reconfigure, or delete anything/i)).toBeVisible();
  expect(screen.queryByRole("button", { name: /Add New_Player/ })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Run read-only checks" }));
  expect(await screen.findByText("Blockstead found a confirmed problem")).toBeVisible();
  const results = within(screen.getByLabelText("Troubleshooting results"));
  expect(results.getByText("Needs attention · confirmed")).toBeVisible();
  expect(screen.getByRole("button", { name: "Review repair" })).toBeVisible();
});

test("requires a separate permission review before applying a bounded repair", async () => {
  renderWizard((url, init) => {
    if (url.endsWith("/troubleshooting/problems")) return respond(catalog);
    if (url.endsWith("/troubleshooting/assess")) return respond(assessment);
    if (url.endsWith("/troubleshooting/repair") && init?.method === "POST") {
      return respond({
        status: "accepted",
        detail: "Minecraft accepted the repair command for New_Player. Blockstead will check the evidence again.",
      });
    }
    return respond({});
  });
  const user = userEvent.setup();

  await user.click(await screen.findByRole("radio", { name: /A specific player cannot join/ }));
  await user.type(screen.getByLabelText("Minecraft player name"), "New_Player");
  await user.click(screen.getByRole("button", { name: "Continue to checks" }));
  await user.click(screen.getByRole("button", { name: "Run read-only checks" }));
  await user.click(await screen.findByRole("button", { name: "Review repair" }));

  const dialog = screen.getByRole("dialog", { name: /Review “Add New_Player/ });
  expect(within(dialog).getByText(/Nothing has changed yet/)).toBeVisible();
  expect(within(dialog).getByText(/cannot delete world data/)).toBeVisible();

  await user.click(within(dialog).getByRole("button", { name: "Confirm Add New_Player to the allowlist" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/v1/profiles/profile-1/troubleshooting/repair",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ action_id: "allowlist_add", player_name: "New_Player" }),
    }),
  ));
  expect(await screen.findByText(/Minecraft accepted the repair command/)).toBeVisible();
});

test("can report no confirmed solution without presenting an unsafe action", async () => {
  const noSolution: TroubleshootingAssessment = {
    ...assessment,
    problem: catalog.problems[1],
    outcome: "incomplete",
    headline: "No confirmed cause was found",
    detail: "Some checks could not be completed.",
    checks: [
      {
        id: "external-port",
        label: "Router-facing Minecraft port is reachable",
        status: "unknown",
        certainty: "none",
        detail: "A check from inside this network cannot prove the router mapping.",
        source_ids: ["minecraft-server-setup"],
      },
    ],
    actions: [],
    next_steps: ["Ask someone on another network to test."],
    sources: [catalog.sources[1]],
  };
  renderWizard(url =>
    respond(url.endsWith("/troubleshooting/problems") ? catalog : noSolution),
  );
  const user = userEvent.setup();

  await user.click(await screen.findByRole("radio", { name: /Friends outside my network/ }));
  await user.click(screen.getByRole("button", { name: "Continue to checks" }));
  await user.click(screen.getByRole("button", { name: "Run read-only checks" }));

  expect(await screen.findByText("No confirmed cause was found")).toBeVisible();
  expect(screen.getByText(/cannot prove the router mapping/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Review repair" })).not.toBeInTheDocument();
});
