export interface ApiError { error: { code: string; message: string; recovery?: string } }
export interface Session { username: string; csrf_token?: string }
export interface Profile { id: string; name: string; server_directory: string; distribution: string; minecraft_version: string | null; loader_version: string | null; is_fixture: boolean }
export interface ProcessState { state: "STOPPED" | "STARTING" | "RUNNING" | "STOPPING" | "CRASHED" | "DEGRADED" | "UNKNOWN"; pid: number | null; exit_code: number | null; reason: string; started_at?: string | null; profile_id?: string | null }
export interface LogEvent { sequence: number; timestamp: string; line: string; profile_id: string | null }
export interface ImportScan { canonical_path: string; distribution: string; minecraft_version: string | null; detected_files: string[]; is_fixture: boolean; plan: string[] }
export type SettingCategory = "Gameplay" | "Players" | "World" | "Network" | "Performance"
export type SettingValue = string | number | boolean
export interface SettingEntry { key: string; label: string; category: SettingCategory; description: string; type: "string" | "integer" | "boolean"; value: SettingValue | null; minimum: number | null; maximum: number | null; options: string[]; restart_required: boolean }
export interface SettingsView { present: boolean; revision: string | null; settings: SettingEntry[]; other_keys: string[] }
export interface SettingChange { key: string; value: SettingValue }
export interface SettingDiff { key: string; label: string; category: SettingCategory; before: SettingValue | null; after: SettingValue; restart_required: boolean }
export interface SettingsPreview { revision: string; changes: SettingDiff[]; restart_required: boolean }
export interface SettingsApplyResult extends SettingsPreview { snapshot_name: string; previous_revision: string; view: SettingsView }
export interface RawSettingsView { present: boolean; editable: boolean; problem: string | null; revision: string | null; content: string | null; secret_keys: string[] }
export interface RawSettingsPreview { revision: string; valid: boolean; problems: string[]; no_changes: boolean; changed_known: SettingDiff[]; removed_known: string[]; other_lines_changed: boolean; restart_required: boolean }
export interface RawSettingsApplyResult { snapshot_name: string; previous_revision: string; revision: string; changed_known: SettingDiff[]; removed_known: string[]; other_lines_changed: boolean; restart_required: boolean; view: SettingsView }
export interface PlayerEntry { name: string; uuid: string | null; level: number | null; reason: string | null }
export interface PlayerFile { present: boolean; readable: boolean; players: PlayerEntry[] }
export interface PlayersView { allowlist: PlayerFile; operators: PlayerFile; bans: PlayerFile }
export type PlayerAction = "whitelist_add" | "whitelist_remove" | "op" | "deop" | "ban" | "pardon"
export interface SystemMetrics { cpu_percent: number; memory: { total_bytes: number; used_bytes: number; percent: number }; disk: { total_bytes: number; used_bytes: number; percent: number }; process: { uptime_seconds: number | null; memory_bytes: number | null } }
export interface OverviewMetricPoint { at: string; cpu_percent: number; memory_percent: number; disk_percent: number; process_memory_bytes: number | null; world_size_bytes: number | null }
export interface OverviewWarning { code: string; title: string; detail: string; to: string; severity: "warning" | "danger" }
export interface OverviewActivity { id: string; category: string; result: string; detail: string; created_at: string; to: string }
export interface ProfileOverview {
  state: { value: ProcessState["state"]; reason: string; uptime_seconds: number | null };
  join: { host: string; port: number; address: string; bind_address: string | null; candidate_hosts: string[]; local_only: boolean };
  players: { online: number | null; max: number; sample: string[]; available: boolean };
  metrics: { current: OverviewMetricPoint & { memory_used_bytes: number; memory_total_bytes: number; disk_used_bytes: number; disk_total_bytes: number }; history: OverviewMetricPoint[] };
  last_backup: BackupRecord | null;
  next_operation: { label: string; at: string } | null;
  warnings: OverviewWarning[];
  activity: OverviewActivity[];
  capabilities: { tps: boolean; mspt: boolean; distribution_label: string };
}
export interface Schedule { id: string; profile_id: string; enabled: boolean; start_time: string | null; stop_time: string | null; backup_before_stop: boolean; power_off_after_stop: boolean; wake_time: string | null }
export interface BackupRecord { id: string; profile_id: string; status: "in_progress" | "completed" | "failed" | "expired"; method: "world_archive"; trigger: "manual" | "schedule"; file_name: string | null; size_bytes: number | null; duration_ms: number | null; sha256: string | null; included_paths: string[]; archive_available: boolean; result: string; created_at: string; completed_at: string | null }
export interface RestorePreview { backup_id: string; verified: boolean; sha256: string; size_bytes: number; included_paths: string[]; worlds_replaced: string[]; required_bytes: number; available_bytes: number; backup_created_at: string | null; minecraft_version: string | null; can_restore: boolean; blockers: string[] }
export interface RestoreResult { restored_paths: string[]; preserved_paths: string[]; result: string }
export interface BackupPolicy { keep_count: number | null; keep_days: number | null; max_total_mb: number | null }
export interface JavaRuntime { path: string; version: string; major: number }
export interface PrerequisitesView { distribution: string; label: string; minecraft_version: string | null; is_fixture: boolean; eula_accepted: boolean; required_java_major: number | null; java_runtimes: JavaRuntime[]; selected_java: JavaRuntime | null; java_satisfied: boolean; launch_files_ready: boolean; launch_problem: string | null; extension_directory: string | null; extension_directory_present: boolean }
export interface ExtensionEntry { file_name: string; size_bytes: number; sha256: string | null; kind: "paper-plugin" | "fabric-mod" | "quilt-mod" | "neoforge-mod" | "forge-mod" | "unknown"; loaders: string[]; identifier: string | null; display_name: string | null; version: string | null; minecraft_constraint: string | null; environment: string | null; dependencies: string[]; readable: boolean }
export interface ExtensionWarning { code: string; message: string; files: string[] }
export interface ExtensionsView { directory: string | null; present: boolean; entries: ExtensionEntry[]; disabled_entries: ExtensionEntry[]; warnings: ExtensionWarning[]; truncated: boolean }
export interface CatalogProject { project_id: string; slug: string | null; title: string | null; description: string | null; downloads: number | null; icon_url?: string | null; author?: string | null; project_type?: string | null }
export interface CatalogSearch { minecraft_version?: string | null; projects: CatalogProject[] }
export interface ModpackInstallResult { id: string; name: string; directory: string; distribution: string; minecraft_version: string; loader_version: string | null; installed_files: number; override_files: number; skipped_unsupported: string[]; notes: string[]; eula_accepted: boolean }
export interface ProvisionVersions { distribution: string; versions: string[] }
export interface ProvisionResult { id: string; name: string; distribution: string; minecraft_version: string; loader_version: string | null; directory: string; notes: string[]; eula_accepted: boolean }
export interface ModConfigEntry { path: string; size_bytes: number }
export interface ModConfigsView { distribution: string; directory: string; files: ModConfigEntry[] }
export interface ModConfigDocument { path: string; content: string; revision: string; size_bytes: number; restart_required?: boolean }

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
