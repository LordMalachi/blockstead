import { describe, expect, test } from "vitest";
import { normalizeServerDirectoryName, SERVER_DIRECTORY_PATTERN } from "./server-directory";

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
});
