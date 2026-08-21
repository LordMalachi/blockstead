import { vi } from "vitest";
import { api, apiBlob, ApiRequestError, fieldErrorsOf } from "./client";

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("keeps the flattened message unchanged while attaching structured fields", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond({
    error: {
      code: "REQUEST_INVALID",
      message: "Some submitted information was invalid.",
      recovery: "Review the highlighted fields and try again.",
      fields: [{
        field: "directory_name",
        reason: "INVALID_CHARACTERS",
        message: "Use only lowercase letters, numbers, hyphens and underscores.",
        rule: "Start with a lowercase letter or number, then up to 63 more lowercase letters, numbers, hyphens or underscores.",
        suggestion: "family-server",
      }],
    },
  }, 422)));

  await expect(api("/provision", { method: "POST" })).rejects.toMatchObject({
    message: "Some submitted information was invalid. Review the highlighted fields and try again.",
    code: "REQUEST_INVALID",
    recovery: "Review the highlighted fields and try again.",
    status: 422,
  });
});

test("fieldErrorsOf maps failures by field name", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond({
    error: { code: "REQUEST_INVALID", message: "Invalid.", fields: [{ field: "directory_name", reason: "TOO_LONG", message: "Too long." }] },
  }, 422)));

  let caught: unknown;
  try {
    await api("/provision", { method: "POST" });
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(ApiRequestError);
  const fields = fieldErrorsOf(caught);
  expect(fields.get("directory_name")).toMatchObject({ reason: "TOO_LONG", message: "Too long." });
  expect(fields.has("other_field")).toBe(false);
});

test("fieldErrorsOf returns an empty map for errors without a fields array", () => {
  expect(fieldErrorsOf(new Error("boom")).size).toBe(0);
  expect(fieldErrorsOf(new ApiRequestError("boom", 400, { error: { code: "X", message: "boom" } })).size).toBe(0);
});

test("a request without a fields array still throws with an empty fields list", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond({ error: { code: "NOT_FOUND", message: "Not found." } }, 404)));

  await expect(api("/profiles/missing")).rejects.toMatchObject({ message: "Not found.", code: "NOT_FOUND", fields: [] });
});

test("apiBlob keeps its existing message shape (no recovery appended) while carrying the code", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond({ error: { code: "NOT_FOUND", message: "Not found.", recovery: "Try again." } }, 404)));

  await expect(apiBlob("/backups/x")).rejects.toMatchObject({ message: "Not found.", code: "NOT_FOUND", status: 404 });
});
