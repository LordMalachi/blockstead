import { describe, expect, test } from "vitest";
import { describeServerDirectoryName, normalizeServerDirectoryName, SERVER_DIRECTORY_PATTERN } from "./server-directory";

describe("normalizeServerDirectoryName", () => {
  test("creates a valid portable folder from a display label", () => {
    const folder = normalizeServerDirectoryName("Boney420-Paper");

    expect(folder).toBe("boney420-paper");
    expect(SERVER_DIRECTORY_PATTERN.test(folder)).toBe(true);
  });

  test("removes unsupported leading and trailing characters", () => {
    expect(normalizeServerDirectoryName(" __Family Server!! ")).toBe("family-server");
    expect(normalizeServerDirectoryName("***", "modded-server")).toBe("modded-server");
  });

  // Table from docs/validation-contract.md ("Sanitization must agree on both sides") —
  // also asserted by the backend at backend/tests/test_validation.py
  // (SANITIZER_TABLE). Both implementations must produce identical output for identical
  // input.
  //
  // The doc's own worked example lists `"Ünïcødé"` -> `"nc-d"`, but applying the doc's
  // stated rule step by step (lower "Ünïcødé" to "ünïcødé"; its four accented characters
  // — ü, ï, ø, é — are each a disallowed one-character run, so each becomes its own "-",
  // giving "-n-c-d-"; strip the leading and trailing "-" and there is no adjacent
  // separator left to collapse) yields "n-c-d", not "nc-d". "nc-d" isn't reachable from
  // the written rule without an unstated extra step. This is flagged to the team lead as
  // a likely transcription error in the contract doc; "n-c-d" — the rule as written — is
  // asserted below, matching the backend's own resolution of the same discrepancy.
  test.each([
    ["  Family Server  ", "family-server"],
    ["My__Server!!", "my_server"],
    ["---", "minecraft-server"],
    ["Ünïcødé", "n-c-d"],
    ["A".repeat(80), "a".repeat(64)],
  ])("%j → %j", (input, expected) => {
    expect(normalizeServerDirectoryName(input)).toBe(expected);
  });

  test("output always matches the pattern, even for extreme input", () => {
    const samples = ["  Family Server  ", "My__Server!!", "---", "Ünïcødé", "A".repeat(80), "", "already-fine", "123", "_leading_underscore", "trailing-", "a".repeat(200)];
    for (const sample of samples) expect(SERVER_DIRECTORY_PATTERN.test(normalizeServerDirectoryName(sample))).toBe(true);
  });

  test("falls back when nothing survives", () => {
    expect(normalizeServerDirectoryName("")).toBe("minecraft-server");
    expect(normalizeServerDirectoryName("   ")).toBe("minecraft-server");
    expect(normalizeServerDirectoryName("!!!")).toBe("minecraft-server");
    expect(normalizeServerDirectoryName("!!!", "family-server")).toBe("family-server");
  });

  // Hyphen runs and underscore runs each collapse to one of their own kind, independently
  // — not to a single character of whichever kind started the run — matching the
  // backend's two separate substitutions (_REPEATED_HYPHEN, then _REPEATED_UNDERSCORE).
  test("collapses hyphen runs and underscore runs independently", () => {
    expect(normalizeServerDirectoryName("odd--__mix")).toBe("odd-_mix");
  });
});

describe("describeServerDirectoryName", () => {
  test("returns null for an already-valid name", () => {
    expect(describeServerDirectoryName("family-server")).toBeNull();
    expect(describeServerDirectoryName("a")).toBeNull();
    expect(describeServerDirectoryName("server_2")).toBeNull();
  });

  test("flags an empty value as required", () => {
    const description = describeServerDirectoryName("");
    expect(description).toMatchObject({ reason: "REQUIRED", suggestion: "minecraft-server" });
    expect(description?.rule).toBeTruthy();
  });

  test("flags a name over the length limit", () => {
    const description = describeServerDirectoryName("a".repeat(65));
    expect(description).toMatchObject({ reason: "TOO_LONG" });
    expect(description?.suggestion).toBeTruthy();
    expect(description!.suggestion.length).toBeLessThanOrEqual(64);
  });

  test("flags uppercase letters and offers the lowercase suggestion", () => {
    expect(describeServerDirectoryName("Family-Server")).toMatchObject({ reason: "UPPERCASE_NOT_ALLOWED", suggestion: "family-server" });
  });

  test("flags a name that starts with a separator", () => {
    expect(describeServerDirectoryName("-family-server")).toMatchObject({ reason: "MUST_START_WITH_LETTER_OR_NUMBER", suggestion: "family-server" });
  });

  test("flags a name that ends with a separator, even though the bare pattern would allow it", () => {
    expect(SERVER_DIRECTORY_PATTERN.test("family-server-")).toBe(true);
    expect(describeServerDirectoryName("family-server-")).toMatchObject({ reason: "MUST_END_WITH_LETTER_OR_NUMBER", suggestion: "family-server" });
  });

  test("flags stray symbols as invalid characters", () => {
    expect(describeServerDirectoryName("family server!")).toMatchObject({ reason: "INVALID_CHARACTERS", suggestion: "family-server" });
  });

  // The pattern alone permits repeated separators mid-string; describeServerDirectoryName
  // agrees it's valid there too (matching the backend, which never emits
  // CONSECUTIVE_SEPARATORS for this field).
  test("accepts repeated separators mid-string, since the pattern allows them", () => {
    expect(SERVER_DIRECTORY_PATTERN.test("family--server")).toBe(true);
    expect(describeServerDirectoryName("family--server")).toBeNull();
  });

  test("every description's suggestion always passes validation", () => {
    for (const input of ["", "A".repeat(90), "Family-Server", "-lead", "trail-", "bad name!"]) {
      const description = describeServerDirectoryName(input);
      expect(description).not.toBeNull();
      expect(SERVER_DIRECTORY_PATTERN.test(description!.suggestion)).toBe(true);
    }
  });
});
