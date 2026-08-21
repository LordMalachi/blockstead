import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { ModpacksPanel } from "./ModpacksPanel";

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// jsdom's `new FormData(form)` never serializes `<input type="file">` values (a
// long-standing jsdom gap, not a browser one), so `uploadPack`'s
// `new FormData(form)` call would see an empty file field here no matter how the file
// input is populated in the test. This test-only shim rebuilds the form data from the
// live DOM elements — including the file input's `.files` — so the file the test
// selects actually reaches the component's submit handler, matching real-browser
// behavior. Scoped to this file only; production code and other tests are unaffected.
const NativeFormData = globalThis.FormData;
class FormElementAwareFormData extends NativeFormData {
  constructor(form?: HTMLFormElement) {
    super();
    if (!form) return;
    for (const element of Array.from(form.elements)) {
      if (!(element instanceof HTMLInputElement) || !element.name) continue;
      if (element.type === "file") { for (const file of Array.from(element.files ?? [])) this.append(element.name, file); }
      else if (element.type !== "checkbox" && element.type !== "radio") this.append(element.name, element.value);
      else if (element.checked) this.append(element.name, element.value);
    }
  }
}
vi.stubGlobal("FormData", FormElementAwareFormData);

const searchResults = { projects: [{ project_id: "proj-1", slug: "cottage-life", title: "Cottage Life", description: "Cozy adventure pack." }] };
const installResult = { id: "new-profile", name: "Cottage Life", directory: "/srv/cottage-life", distribution: "fabric", minecraft_version: "1.21.1", loader_version: "1", installed_files: 4, override_files: 1, skipped_unsupported: [], notes: [], eula_accepted: false };

function renderPanel(options: { installResponse?: () => Response; uploadResponse?: () => Response } = {}) {
  const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/modpacks/search")) return Promise.resolve(respond(searchResults));
    if (url.includes("/modpacks/install")) return Promise.resolve(options.installResponse ? options.installResponse() : respond(installResult, 201));
    if (url.includes("/modpacks/upload") && init) return Promise.resolve(options.uploadResponse ? options.uploadResponse() : respond(installResult, 201));
    return Promise.resolve(respond({}, 200));
  });
  vi.stubGlobal("fetch", fetch);
  const onCreated = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ModpacksPanel stopped onCreated={onCreated} /></QueryClientProvider>);
  return { fetch, onCreated };
}

async function chooseModpack() {
  fireEvent.change(screen.getByLabelText("Search Modrinth modpacks"), { target: { value: "cottage" } });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  fireEvent.click(await screen.findByRole("button", { name: "Choose" }));
}

test("choosing a modpack pre-fills a name and folder that already pass the pattern", async () => {
  renderPanel();
  await chooseModpack();

  const name = screen.getByLabelText<HTMLInputElement>("Profile name", { selector: "input:not([name])" });
  const directory = screen.getByLabelText<HTMLInputElement>("Server folder", { selector: "input:not([name])" });
  expect(name.value).toBe("Cottage Life");
  expect(directory.value).toBe("cottage-life");
  expect(directory).not.toHaveAttribute("aria-invalid");
});

test("installs the chosen modpack", async () => {
  const { fetch, onCreated } = renderPanel();
  await chooseModpack();
  fireEvent.click(screen.getByRole("button", { name: "Install modpack" }));

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new-profile"));
  expect(fetch).toHaveBeenCalledWith("/api/v1/modpacks/install", expect.objectContaining({
    method: "POST",
    body: JSON.stringify({ name: "Cottage Life", directory_name: "cottage-life", project_id: "proj-1" }),
  }));
});

test("shows a live suggestion while typing an invalid install folder name", async () => {
  renderPanel();
  await chooseModpack();
  const directory = screen.getByLabelText("Server folder", { selector: "input:not([name])" });

  fireEvent.change(directory, { target: { value: "Cottage Life!!" } });

  expect(directory).toHaveAttribute("aria-invalid", "true");
  expect(directory).toHaveClass("field-invalid");
  fireEvent.click(screen.getByRole("button", { name: /Use suggested name.*cottage-life/ }));
  expect(directory).toHaveValue("cottage-life");
  expect(directory).not.toHaveAttribute("aria-invalid");
});

test("highlights the install folder field when the server rejects it", async () => {
  const { onCreated } = renderPanel({
    installResponse: () => respond({
      error: {
        code: "REQUEST_INVALID",
        message: "Some submitted information was invalid.",
        recovery: "Review the highlighted fields and try again.",
        fields: [{ field: "directory_name", reason: "ALREADY_EXISTS", message: "A server already uses this folder name.", rule: null, suggestion: "cottage-life-2" }],
      },
    }, 422),
  });
  await chooseModpack();
  fireEvent.click(screen.getByRole("button", { name: "Install modpack" }));

  const directory = await screen.findByLabelText("Server folder", { selector: "input:not([name])" });
  await waitFor(() => expect(directory).toHaveAttribute("aria-invalid", "true"));
  expect(screen.getByText("A server already uses this folder name.")).toBeVisible();
  expect(onCreated).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: /Use suggested name.*cottage-life-2/ }));
  expect(directory).toHaveValue("cottage-life-2");
});

test("shows a live suggestion while typing an invalid upload folder name, and applies the fix", () => {
  renderPanel();
  const directory = screen.getByLabelText("Server folder", { selector: "input[name='directory_name']" });

  fireEvent.change(directory, { target: { value: "My Pack!!" } });

  expect(directory).toHaveAttribute("aria-invalid", "true");
  fireEvent.click(screen.getByRole("button", { name: /Use suggested name.*my-pack/ }));
  expect(directory).toHaveValue("my-pack");
  expect(directory).not.toHaveAttribute("aria-invalid");
});

// jsdom (unlike real browsers) never marks a `required` file input as satisfied by
// fireEvent/userEvent file selection, so a click on the submit button gets silently
// suppressed by native constraint validation before React ever sees it. Submitting the
// form directly exercises the same onSubmit handler without that jsdom-only gap.
function submitUploadForm() {
  fireEvent.submit(document.querySelector(".upload-form")!);
}

test("uploads a local pack with the controlled, normalized field values", async () => {
  const { fetch, onCreated } = renderPanel();
  fireEvent.change(screen.getByLabelText("Profile name", { selector: "input[name='name']" }), { target: { value: "Local Pack" } });
  const directory = screen.getByLabelText("Server folder", { selector: "input[name='directory_name']" });
  fireEvent.change(directory, { target: { value: "Local Pack!!" } });
  // Blurring lets the same live-normalization the owner would see in the browser run
  // before submit, matching real usage (type, tab away, then submit).
  fireEvent.blur(directory);
  const file = new File(["pack"], "pack.mrpack", { type: "application/zip" });
  fireEvent.change(screen.getByLabelText("Modrinth pack file"), { target: { files: [file] } });
  submitUploadForm();

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new-profile"));
  const call = fetch.mock.calls.find(([url]) => (typeof url === "string" ? url : url instanceof URL ? url.href : url.url).includes("/modpacks/upload"));
  expect(call).toBeDefined();
  const body = call![1]!.body as FormData;
  expect(body.get("name")).toBe("Local Pack");
  expect(body.get("directory_name")).toBe("local-pack");
});

test("highlights the upload folder field when the server rejects it", async () => {
  renderPanel({
    uploadResponse: () => respond({
      error: {
        code: "REQUEST_INVALID",
        message: "Some submitted information was invalid.",
        recovery: "Review the highlighted fields and try again.",
        fields: [{ field: "directory_name", reason: "INVALID_CHARACTERS", message: "Use only lowercase letters, numbers, hyphens and underscores.", rule: null, suggestion: "local-pack" }],
      },
    }, 422),
  });
  fireEvent.change(screen.getByLabelText("Profile name", { selector: "input[name='name']" }), { target: { value: "Local Pack" } });
  const directory = screen.getByLabelText("Server folder", { selector: "input[name='directory_name']" });
  fireEvent.change(directory, { target: { value: "local-pack" } });
  const file = new File(["pack"], "pack.mrpack", { type: "application/zip" });
  fireEvent.change(screen.getByLabelText("Modrinth pack file"), { target: { files: [file] } });
  submitUploadForm();

  await waitFor(() => expect(directory).toHaveAttribute("aria-invalid", "true"));
  expect(screen.getByText("Use only lowercase letters, numbers, hyphens and underscores.")).toBeVisible();
});
