import { scopeFor } from "./scope";
import type { ProcessState, Profile } from "../../api/client";

const profile = (id: string, name: string): Profile => ({ id, name, server_directory: `/srv/${id}`, distribution: "vanilla", minecraft_version: "1.21", loader_version: null, is_fixture: true });
const home = profile("home", "Home world");
const creative = profile("creative", "Creative world");
const snapshot = (over: Partial<ProcessState>): ProcessState => ({ state: "STOPPED", pid: null, exit_code: null, reason: "Stopped", ...over });

test("reports the managed process against the profile that owns it", () => {
  const scope = scopeFor(home, snapshot({ state: "RUNNING", pid: 4242, reason: "Server is running", profile_id: "home" }), [home, creative]);
  expect(scope.isActive).toBe(true);
  expect(scope.running).toBe(true);
  expect(scope.pid).toBe(4242);
  expect(scope.occupant).toBeNull();
});

test("never attributes another profile's running process to this profile", () => {
  const scope = scopeFor(creative, snapshot({ state: "RUNNING", pid: 4242, reason: "Server is running", profile_id: "home" }), [home, creative]);
  expect(scope.state).toBe("STOPPED");
  expect(scope.running).toBe(false);
  expect(scope.pid).toBeNull();
  expect(scope.occupant).toEqual(home);
  expect(scope.canStart).toBe(false);
  expect(scope.reason).toContain("Home world");
});

test("frees the start action once the other profile's process has gone", () => {
  const scope = scopeFor(creative, snapshot({ state: "CRASHED", exit_code: 1, reason: "Server crashed", profile_id: "home" }), [home, creative]);
  expect(scope.state).toBe("STOPPED");
  expect(scope.exitCode).toBeNull();
  expect(scope.occupant).toBeNull();
  expect(scope.canStart).toBe(true);
});

test("surfaces this profile's own crash for recovery", () => {
  const scope = scopeFor(home, snapshot({ state: "CRASHED", exit_code: 1, reason: "Server crashed", profile_id: "home" }), [home]);
  expect(scope.state).toBe("CRASHED");
  expect(scope.exitCode).toBe(1);
  expect(scope.stopped).toBe(true);
  expect(scope.canStart).toBe(true);
});
