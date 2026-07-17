import { useOutletContext } from "react-router-dom";
import type { ProcessState, Profile } from "../../api/client";

const BUSY = ["STARTING", "RUNNING", "STOPPING", "DEGRADED"];

export interface ServerScope {
  profile: Profile;
  /** Process state as it applies to this profile, never another profile's. */
  state: ProcessState["state"];
  reason: string;
  pid: number | null;
  exitCode: number | null;
  startedAt: string | null;
  /** The managed process currently belongs to this profile. */
  isActive: boolean;
  running: boolean;
  stopped: boolean;
  canStart: boolean;
  /** Blockstead runs one server at a time; this is the profile holding the process. */
  occupant: Profile | null;
}

export const useServerScope = () => useOutletContext<ServerScope>();

export function scopeFor(profile: Profile, snapshot: ProcessState, profiles: Profile[]): ServerScope {
  const isActive = snapshot.profile_id === profile.id;
  const busy = BUSY.includes(snapshot.state);
  const occupant = !isActive && busy ? profiles.find(other => other.id === snapshot.profile_id) ?? null : null;
  const state = isActive ? snapshot.state : "STOPPED";
  const reason = isActive
    ? snapshot.reason
    : occupant
      ? `${occupant.name} is using the managed server process. Blockstead runs one server at a time.`
      : "This server is not running.";
  return {
    profile,
    state,
    reason,
    pid: isActive ? snapshot.pid : null,
    exitCode: isActive ? snapshot.exit_code : null,
    startedAt: isActive ? snapshot.started_at ?? null : null,
    isActive,
    running: state === "RUNNING",
    stopped: ["STOPPED", "CRASHED"].includes(state),
    canStart: !occupant && ["STOPPED", "CRASHED", "DEGRADED"].includes(state),
    occupant,
  };
}
