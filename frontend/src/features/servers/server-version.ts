import type { Profile } from "../../api/client";

type VersionProfile = Pick<Profile, "distribution" | "minecraft_version" | "loader_version" | "paper_build">;

const DISTRIBUTION_LABELS: Record<string, string> = {
  vanilla: "Vanilla",
  paper: "Paper",
  fabric: "Fabric",
  forge: "Forge",
  quilt: "Quilt",
  neoforge: "NeoForge",
};

export function serverSoftwareLabel(profile: VersionProfile): string {
  return DISTRIBUTION_LABELS[profile.distribution] ?? profile.distribution;
}

export function serverSoftwareVersion(profile: VersionProfile): string {
  if (profile.distribution === "paper") {
    return profile.paper_build != null ? `Build ${profile.paper_build}` : "Build not recorded";
  }
  if (profile.distribution === "vanilla") return "Same as Minecraft";
  return profile.loader_version ? `Loader ${profile.loader_version}` : "Version not recorded";
}

export function serverSoftwareIdentity(profile: VersionProfile): string {
  const software = serverSoftwareLabel(profile);
  const version = serverSoftwareVersion(profile);
  return profile.distribution === "vanilla" ? software : `${software} · ${version.toLowerCase()}`;
}
