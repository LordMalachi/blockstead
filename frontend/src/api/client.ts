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

let csrfToken = sessionStorage.getItem("blockstead_csrf") ?? "";
export const setCsrf = (value: string) => { csrfToken = value; sessionStorage.setItem("blockstead_csrf", value); };
export const clearCsrf = () => { csrfToken = ""; sessionStorage.removeItem("blockstead_csrf"); };
export const getCsrf = () => csrfToken;

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    const body = await response.json() as ApiError;
    throw new Error(body.error?.recovery ? `${body.error.message} ${body.error.recovery}` : body.error?.message ?? "Request failed.");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
