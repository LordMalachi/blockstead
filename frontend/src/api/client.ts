export interface ApiError { error: { code: string; message: string; recovery?: string } }
export interface Session { username: string; csrf_token?: string }
export interface Profile { id: string; name: string; server_directory: string; distribution: string; minecraft_version: string | null; loader_version: string | null; is_fixture: boolean }
export interface ProcessState { state: "STOPPED" | "STARTING" | "RUNNING" | "STOPPING" | "CRASHED" | "DEGRADED" | "UNKNOWN"; pid: number | null; exit_code: number | null; reason: string; started_at?: string | null; profile_id?: string | null }
export interface LogEvent { sequence: number; timestamp: string; line: string; profile_id: string | null }
export interface ImportScan { canonical_path: string; distribution: string; minecraft_version: string | null; detected_files: string[]; is_fixture: boolean; plan: string[] }
export interface ImportUploadStartResult { upload_id: string }
export interface ImportUploadResult extends ImportScan { id: string; name: string }
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
export interface CommandOption { value: string; label: string; icon?: string }
export interface CommandArgument {
  key: string;
  label: string;
  kind: "text" | "player" | "integer" | "choice" | "resource" | "boolean";
  required: boolean;
  placeholder?: string;
  source?: "players";
  allow_selectors?: boolean;
  options?: Array<string | CommandOption>;
  suggestions?: number[];
  minimum?: number;
  maximum?: number;
  max_length?: number;
}
export interface GuidedCommand { id: string; label: string; root: string; category: string; description: string; safety: "normal" | "caution" | "danger"; arguments: CommandArgument[] }
export interface CommandCatalog { schema_version: number; revision: string; source: "curated" | "runtime"; complete: boolean; commands: GuidedCommand[] }
export interface SystemMetrics { cpu_percent: number; memory: { total_bytes: number; used_bytes: number; percent: number }; disk: { total_bytes: number; used_bytes: number; percent: number }; process: { uptime_seconds: number | null; memory_bytes: number | null } }
export interface DiagnosticLogEntry { at: string; level: string; logger: string; message: string }
export interface DiagnosticsReport {
  report_version: number;
  generated_at: string;
  application: { version: string; python: string; platform: string };
  settings: { bind_host: string; port: number; data_dir: string; server_root: string; secure_cookies: boolean; session_hours: number; allowed_origins: string[]; static_dir_present: boolean };
  host: { cpu_percent: number; memory: { total_bytes: number; used_bytes: number; percent: number }; disk: { total_bytes: number; used_bytes: number; percent: number }; uptime_seconds: number };
  java_runtimes: JavaRuntime[];
  server: ProcessState;
  profiles: Array<{ id: string; name: string; distribution: string; minecraft_version: string | null; loader_version: string | null; is_fixture: boolean; directory: string }>;
  schedules: Array<{ profile_id: string; enabled: boolean; start_time: string | null; stop_time: string | null; weekdays: string }>;
  recent_automation_runs: Array<{ trigger: string; action: string; status: string; detail: string; started_at: string }>;
  recent_backups: Array<{ status: string; trigger: string; size_bytes: number | null; duration_ms: number | null; result: string; created_at: string }>;
  audit_tail: Array<{ category: string; result: string; detail: string; created_at: string }>;
  recent_errors: DiagnosticLogEntry[];
  recent_log: DiagnosticLogEntry[];
}
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
export interface AutomationExecution { kind: "recurring" | "one_time"; action: "start" | "maintenance"; label: string; at: string; steps: string[] }
export interface AutomationEvent { id: string; run_at: string; backup_before_stop: boolean; power_off_after_stop: boolean; wake_time: string | null; only_when_empty: boolean }
export interface AutomationRun { id: string; trigger: "scheduled" | "one_time" | "manual"; action: "start" | "maintenance"; status: "success" | "failed" | "skipped"; steps: string[]; detail: string; duration_ms: number; started_at: string; completed_at: string }
export interface Schedule { id: string; profile_id: string; enabled: boolean; start_time: string | null; stop_time: string | null; backup_before_stop: boolean; power_off_after_stop: boolean; wake_time: string | null; weekdays: number[]; only_when_empty: boolean; power_capable: boolean; maintenance_steps: string[]; next_executions: AutomationExecution[]; one_time_events: AutomationEvent[]; history: AutomationRun[] }
export interface AutomationCapabilities { host_power: boolean }
export interface BackupRecord { id: string; profile_id: string; status: "in_progress" | "completed" | "failed" | "expired"; method: "world_archive"; trigger: "manual" | "schedule"; file_name: string | null; size_bytes: number | null; duration_ms: number | null; sha256: string | null; included_paths: string[]; archive_available: boolean; result: string; created_at: string; completed_at: string | null }
export interface RestorePreview { backup_id: string; verified: boolean; sha256: string; size_bytes: number; included_paths: string[]; worlds_replaced: string[]; required_bytes: number; available_bytes: number; backup_created_at: string | null; minecraft_version: string | null; can_restore: boolean; blockers: string[] }
export interface RestoreResult { restored_paths: string[]; preserved_paths: string[]; result: string }
export interface BackupPolicy { keep_count: number | null; keep_days: number | null; max_total_mb: number | null }
export interface JavaRuntime { path: string; version: string; major: number }
export interface PrerequisitesView { distribution: string; label: string; minecraft_version: string | null; is_fixture: boolean; eula_accepted: boolean; required_java_major: number | null; java_runtimes: JavaRuntime[]; selected_java: JavaRuntime | null; java_satisfied: boolean; launch_files_ready: boolean; launch_problem: string | null; extension_directory: string | null; extension_directory_present: boolean }
export interface ExtensionEntry { file_name: string; size_bytes: number; sha256: string | null; kind: "paper-plugin" | "fabric-mod" | "quilt-mod" | "neoforge-mod" | "forge-mod" | "unknown"; loaders: string[]; identifier: string | null; display_name: string | null; version: string | null; minecraft_constraint: string | null; environment: string | null; dependencies: string[]; readable: boolean }
export interface ExtensionWarning { code: string; message: string; files: string[] }
export interface ExtensionsView { directory: string | null; present: boolean; entries: ExtensionEntry[]; disabled_entries: ExtensionEntry[]; warnings: ExtensionWarning[]; truncated: boolean }
export interface SharedMapView { config_present: boolean; config_path: string | null; internal_webserver_enabled: boolean; bind: string; port: number; problem: string | null }
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

// Sessions expire server-side; without this hook a signed-out dashboard keeps
// rendering its last successful data forever. App registers a handler that
// returns the owner to the sign-in screen the moment any request comes back 401.
let onAuthExpired: (() => void) | null = null;
export const setOnAuthExpired = (handler: (() => void) | null) => { onAuthExpired = handler; };
const reportAuthExpired = (status: number) => { if (status === 401) { clearCsrf(); onAuthExpired?.(); } };

/** POST a FormData body with upload progress, which fetch cannot report. */
export function apiUpload<T>(path: string, form: FormData, onProgress?: (loadedBytes: number, totalBytes: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `/api/v1${path}`);
    request.responseType = "json";
    request.setRequestHeader("X-CSRF-Token", csrfToken);
    if (onProgress) request.upload.onprogress = event => { if (event.lengthComputable) onProgress(event.loaded, event.total); };
    request.onerror = () => reject(new Error("The upload could not reach Blockstead. Check that the dashboard is still running and try again."));
    request.onload = () => {
      const body = request.response as (ApiError & T) | null;
      if (request.status >= 200 && request.status < 300) resolve(body as T);
      else {
        reportAuthExpired(request.status);
        reject(new Error(body?.error?.recovery ? `${body.error.message} ${body.error.recovery}` : body?.error?.message ?? "Upload failed."));
      }
    };
    request.send(form);
  });
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    reportAuthExpired(response.status);
    const body = await response.json() as ApiError;
    throw new Error(body.error?.recovery ? `${body.error.message} ${body.error.recovery}` : body.error?.message ?? "Request failed.");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
