export interface ApiError { error: { code: string; message: string; recovery?: string } }
export interface Session { username: string; csrf_token?: string }
export interface Profile { id: string; name: string; server_directory: string; distribution: string; minecraft_version: string | null; is_fixture: boolean }
export interface ProcessState { state: "STOPPED" | "STARTING" | "RUNNING" | "STOPPING" | "CRASHED" | "DEGRADED" | "UNKNOWN"; pid: number | null; exit_code: number | null; reason: string; started_at?: string | null; profile_id?: string | null }
export interface LogEvent { sequence: number; timestamp: string; line: string }
export interface ImportScan { canonical_path: string; distribution: string; minecraft_version: string | null; detected_files: string[]; is_fixture: boolean; plan: string[] }
export interface SettingEntry { key: string; label: string; type: "string" | "integer" | "boolean"; value: string | number | boolean | null }
export interface SettingsView { present: boolean; settings: SettingEntry[]; other_keys: string[] }
export interface PlayerEntry { name: string; uuid: string | null; level: number | null; reason: string | null }
export interface PlayerFile { present: boolean; readable: boolean; players: PlayerEntry[] }
export interface PlayersView { allowlist: PlayerFile; operators: PlayerFile; bans: PlayerFile }
export type PlayerAction = "whitelist_add" | "whitelist_remove" | "op" | "deop" | "ban" | "pardon"
export interface SystemMetrics { cpu_percent: number; memory: { total_bytes: number; used_bytes: number; percent: number }; disk: { total_bytes: number; used_bytes: number; percent: number }; process: { uptime_seconds: number | null; memory_bytes: number | null } }
export interface Schedule { id: string; profile_id: string; enabled: boolean; start_time: string | null; stop_time: string | null; backup_before_stop: boolean; power_off_after_stop: boolean; wake_time: string | null }
export interface JavaRuntime { path: string; version: string; major: number }
export interface PrerequisitesView { distribution: string; label: string; minecraft_version: string | null; is_fixture: boolean; eula_accepted: boolean; required_java_major: number | null; java_runtimes: JavaRuntime[]; selected_java: JavaRuntime | null; java_satisfied: boolean; launch_files_ready: boolean; launch_problem: string | null; extension_directory: string | null; extension_directory_present: boolean }
export interface ExtensionEntry { file_name: string; size_bytes: number; sha256: string | null; kind: "paper-plugin" | "fabric-mod" | "neoforge-mod" | "forge-mod" | "unknown"; loaders: string[]; identifier: string | null; display_name: string | null; version: string | null; minecraft_constraint: string | null; environment: string | null; dependencies: string[]; readable: boolean }
export interface ExtensionWarning { code: string; message: string; files: string[] }
export interface ExtensionsView { directory: string | null; present: boolean; entries: ExtensionEntry[]; disabled_entries: ExtensionEntry[]; warnings: ExtensionWarning[]; truncated: boolean }
export interface CatalogProject { project_id: string; slug: string | null; title: string | null; description: string | null; downloads: number | null }
export interface CatalogSearch { minecraft_version?: string | null; projects: CatalogProject[] }
export interface ModpackInstallResult { id: string; name: string; directory: string; minecraft_version: string; loader_version: string | null; installed_files: number; override_files: number; skipped_unsupported: string[]; notes: string[]; eula_accepted: boolean }

let csrfToken = sessionStorage.getItem("blockstead_csrf") ?? "";
export const setCsrf = (value: string) => { csrfToken = value; sessionStorage.setItem("blockstead_csrf", value); };
export const clearCsrf = () => { csrfToken = ""; sessionStorage.removeItem("blockstead_csrf"); };
export const getCsrf = () => csrfToken;

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    const body = await response.json() as ApiError;
    throw new Error(body.error?.recovery ? `${body.error.message} ${body.error.recovery}` : body.error?.message ?? "Request failed.");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
