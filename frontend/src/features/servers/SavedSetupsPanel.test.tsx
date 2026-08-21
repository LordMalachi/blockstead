import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import type { Profile } from "../../api/client";
import { SavedSetupsPanel } from "./SavedSetupsPanel";

const profiles: Profile[] = [
  { id: "profile-1", name: "Homestead", server_directory: "/servers/home", distribution: "vanilla", minecraft_version: "1.21.1", loader_version: null, is_fixture: false },
];

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderPanel(onReview?: () => Response) {
  const fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/saved-setups")) return Promise.resolve(respond([]));
    if (url.includes("/variants/review")) return Promise.resolve(onReview ? onReview() : respond({}, 200));
    return Promise.resolve(respond({}, 200));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><SavedSetupsPanel profiles={profiles} /></QueryClientProvider>);
  return { fetch };
}

test("renders with no setup groups yet", async () => {
  renderPanel();
  expect(await screen.findByText("0 groups")).toBeVisible();
});

test("highlights the folder field and offers a one-click fix when the review is rejected", async () => {
  const setups = [{
    id: "setup-1",
    name: "Weekend worlds",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    variants: [],
  }];
  const fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/saved-setups")) return Promise.resolve(respond(setups));
    if (url.includes("/variants/review")) return Promise.resolve(respond({
      error: {
        code: "REQUEST_INVALID",
        message: "Some submitted information was invalid.",
        recovery: "Review the highlighted fields and try again.",
        fields: [{
          field: "directory_name",
          reason: "CONSECUTIVE_SEPARATORS",
          message: "Don't use two hyphens or underscores in a row.",
          rule: "Start with a lowercase letter or number, then up to 63 more lowercase letters, numbers, hyphens or underscores.",
          suggestion: "creative-snapshot",
        }],
      },
    }, 422));
    return Promise.resolve(respond({}, 200));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><SavedSetupsPanel profiles={profiles} /></QueryClientProvider>);

  await screen.findByText("Weekend worlds");
  fireEvent.change(screen.getByLabelText("Variant name"), { target: { value: "Creative" } });
  fireEvent.change(screen.getByLabelText("Folder name"), { target: { value: "creative--snapshot" } });
  fireEvent.click(screen.getByRole("button", { name: "Review protected copy" }));

  const directory = await screen.findByLabelText("Folder name");
  await waitFor(() => expect(directory).toHaveAttribute("aria-invalid", "true"));
  expect(screen.getByText("Don't use two hyphens or underscores in a row.")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: /Use suggested name.*creative-snapshot/ }));
  expect(directory).toHaveValue("creative-snapshot");
  expect(directory).not.toHaveAttribute("aria-invalid");
});

test("live-validates the folder name as the owner types, before submitting", async () => {
  const setups = [{
    id: "setup-1",
    name: "Weekend worlds",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    variants: [],
  }];
  const fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/saved-setups")) return Promise.resolve(respond(setups));
    return Promise.resolve(respond({}, 200));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><SavedSetupsPanel profiles={profiles} /></QueryClientProvider>);

  await screen.findByText("Weekend worlds");
  const directory = screen.getByLabelText("Folder name");
  fireEvent.change(directory, { target: { value: "Creative Snapshot!!" } });

  expect(directory).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("button", { name: /Use suggested name.*creative-snapshot/ })).toBeVisible();
  expect(fetch.mock.calls.some(([requestInput]) => {
    const url = typeof requestInput === "string" ? requestInput : requestInput instanceof URL ? requestInput.href : requestInput.url;
    return url.includes("/variants/review");
  })).toBe(false);
});
