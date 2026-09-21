import { describe, expect, test } from "vitest";
import type { Profile } from "../../api/client";
import { serverSoftwareIdentity, serverSoftwareVersion } from "./server-version";

function profile(overrides: Partial<Profile>): Profile {
  return {
    id: "profile-1",
    name: "Home",
    server_directory: "/servers/home",
    distribution: "vanilla",
    minecraft_version: "1.21.8",
    loader_version: null,
    paper_build: null,
    is_fixture: false,
    ...overrides,
  };
}

describe("server version labels", () => {
  test("keeps the Minecraft release separate from the Paper build", () => {
    const paper = profile({ distribution: "paper", paper_build: 205 });

    expect(serverSoftwareIdentity(paper)).toBe("Paper · build 205");
    expect(serverSoftwareVersion(paper)).toBe("Build 205");
  });

  test("labels Fabric's independently recorded loader version", () => {
    const fabric = profile({ distribution: "fabric", loader_version: "0.16.7" });

    expect(serverSoftwareIdentity(fabric)).toBe("Fabric · loader 0.16.7");
    expect(serverSoftwareVersion(fabric)).toBe("Loader 0.16.7");
  });

  test("states when an imported server has no recorded software version", () => {
    expect(serverSoftwareVersion(profile({ distribution: "paper" }))).toBe(
      "Build not recorded",
    );
    expect(serverSoftwareVersion(profile({ distribution: "forge" }))).toBe(
      "Version not recorded",
    );
  });
});
