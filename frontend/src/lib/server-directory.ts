export const SERVER_DIRECTORY_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;

/** Convert a user-facing folder label into the portable server-directory form. */
export function normalizeServerDirectoryName(value: string, fallback = "minecraft-server"): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^[^a-z0-9]+/, "")
    .slice(0, 64)
    .replace(/[^a-z0-9]+$/, "");
  return normalized || fallback;
}
