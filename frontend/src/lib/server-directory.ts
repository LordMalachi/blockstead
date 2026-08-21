export const SERVER_DIRECTORY_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;

// Kept in lockstep with the backend's DIRECTORY_NAME_RULE
// (backend/src/blockstead/validation.py) — the two are shown in the same places (a live,
// pre-submit notice here; a server round-trip there), so mismatched wording would read as
// two different rules to the owner.
const SERVER_DIRECTORY_RULE =
  "Use 1 to 64 characters: lowercase letters, numbers, hyphens and underscores, starting and ending with a letter or number.";

const DISALLOWED_RUN = /[^a-z0-9_-]+/g;
const REPEATED_HYPHEN = /-{2,}/g;
const REPEATED_UNDERSCORE = /_{2,}/g;
const LEADING_NON_ALNUM = /^[^a-z0-9]+/;
const TRAILING_NON_ALNUM = /[^a-z0-9]+$/;
const ALLOWED_EDGE_CHAR = /[a-z0-9]/;

/**
 * Convert a user-facing folder label into the portable server-directory form.
 *
 * Must stay byte-for-byte identical to the backend's `normalize_server_directory_name`
 * (see `docs/validation-contract.md` and `backend/src/blockstead/validation.py`): trim,
 * lowercase, replace every run of disallowed characters with a single "-", collapse
 * repeated hyphens and repeated underscores (each kept as its own character — a run of
 * hyphens collapses to one hyphen, a run of underscores to one underscore, independently),
 * strip leading and trailing non-alphanumerics, truncate to 64 characters, strip trailing
 * non-alphanumerics again, and fall back when nothing survives.
 */
export function normalizeServerDirectoryName(value: string, fallback = "minecraft-server"): string {
  let normalized = value.trim().toLowerCase();
  normalized = normalized.replace(DISALLOWED_RUN, "-");
  normalized = normalized.replace(REPEATED_HYPHEN, "-");
  normalized = normalized.replace(REPEATED_UNDERSCORE, "_");
  normalized = normalized.replace(LEADING_NON_ALNUM, "");
  normalized = normalized.replace(TRAILING_NON_ALNUM, "");
  normalized = normalized.slice(0, 64);
  normalized = normalized.replace(TRAILING_NON_ALNUM, "");
  return normalized || fallback;
}

// The reason codes `describe_directory_name` (backend/src/blockstead/validation.py) can
// actually produce for this field. `CONSECUTIVE_SEPARATORS` is a real entry in the shared
// contract's reason-code list, but the backend never emits it for `directory_name` — its
// pattern permits repeated hyphens/underscores mid-string — so it's not reproduced here
// either; that code belongs to some other field sharing the same enum.
export type ServerDirectoryReason =
  | "REQUIRED"
  | "TOO_LONG"
  | "UPPERCASE_NOT_ALLOWED"
  | "INVALID_CHARACTERS"
  | "MUST_START_WITH_LETTER_OR_NUMBER"
  | "MUST_END_WITH_LETTER_OR_NUMBER";

export interface ServerDirectoryDescription {
  reason: ServerDirectoryReason;
  message: string;
  rule: string;
  suggestion: string;
}

/**
 * Explains, before the request ever leaves the browser, why a folder name would be
 * rejected — mirroring the backend's `describe_directory_name` branch for branch (same
 * reason codes, same messages) so the UI can warn live instead of waiting on a round trip,
 * and so a later server rejection never contradicts what was already shown. Returns `null`
 * when `value` already satisfies `SERVER_DIRECTORY_PATTERN` *and* ends in a letter or
 * number — the pattern alone permits a trailing separator, but the dashboard wants the
 * name to end clean too.
 */
export function describeServerDirectoryName(value: string, fallback = "minecraft-server"): ServerDirectoryDescription | null {
  if (SERVER_DIRECTORY_PATTERN.test(value) && ALLOWED_EDGE_CHAR.test(value[value.length - 1] ?? "")) return null;
  const suggestion = normalizeServerDirectoryName(value, fallback);
  if (!value) {
    return { reason: "REQUIRED", message: "A server folder name is required.", rule: SERVER_DIRECTORY_RULE, suggestion };
  }
  if (value.length > 64) {
    return { reason: "TOO_LONG", message: "Use 64 characters or fewer.", rule: SERVER_DIRECTORY_RULE, suggestion };
  }
  if (value !== value.toLowerCase()) {
    return { reason: "UPPERCASE_NOT_ALLOWED", message: "Use only lowercase letters.", rule: SERVER_DIRECTORY_RULE, suggestion };
  }
  if (/[^a-z0-9_-]/.test(value)) {
    return { reason: "INVALID_CHARACTERS", message: "Use only lowercase letters, numbers, hyphens and underscores.", rule: SERVER_DIRECTORY_RULE, suggestion };
  }
  if (!ALLOWED_EDGE_CHAR.test(value[0] ?? "")) {
    return { reason: "MUST_START_WITH_LETTER_OR_NUMBER", message: "Start the name with a letter or number.", rule: SERVER_DIRECTORY_RULE, suggestion };
  }
  return { reason: "MUST_END_WITH_LETTER_OR_NUMBER", message: "End the name with a letter or number.", rule: SERVER_DIRECTORY_RULE, suggestion };
}
