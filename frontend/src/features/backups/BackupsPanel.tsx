import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  apiBlob,
  type BackupPolicy,
  type BackupRecord,
  type ProcessState,
  type RestorePreview,
  type RestoreResult,
} from "../../api/client";
import { Button } from "../../components/Button";
import { NavIcon } from "../../components/NavIcon";
import { Tooltip } from "../../components/Tooltip";
import { formatBytes } from "../../lib/format";

function formatWhen(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDuration(milliseconds: number | null): string {
  if (milliseconds == null) return "—";
  if (milliseconds < 1000) return `${milliseconds} ms`;
  return `${(milliseconds / 1000).toFixed(1)} s`;
}

function retentionSummary(policy?: BackupPolicy): string {
  if (!policy) return "Loading policy";
  const rules = [
    policy.keep_count == null ? null : `${policy.keep_count} backup${policy.keep_count === 1 ? "" : "s"}`,
    policy.keep_days == null ? null : `${policy.keep_days} day${policy.keep_days === 1 ? "" : "s"}`,
    policy.max_total_mb == null ? null : `${policy.max_total_mb.toLocaleString()} MB`,
  ].filter(Boolean);
  return rules.length ? rules.join(" · ") : "No automatic limit";
}

function statusLabel(record: BackupRecord): string {
  if (record.status === "completed" && !record.archive_available) return "archive missing";
  return record.status.replace("_", " ");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

interface PolicyDraft {
  keep_count: string;
  keep_days: string;
  max_total_mb: string;
  redundancy_enabled: boolean;
  destinations: string[];
}

interface WritableFileHandle {
  createWritable(): Promise<{ write(data: Blob): Promise<void>; close(): Promise<void> }>;
}

interface BackupDirectoryHandle {
  getFileHandle(name: string, options: { create: true }): Promise<WritableFileHandle>;
}

function directoryPicker(): (() => Promise<BackupDirectoryHandle>) | undefined {
  return (window as typeof window & { showDirectoryPicker?: () => Promise<BackupDirectoryHandle> }).showDirectoryPicker;
}

async function saveBackup(profileId: string, backup: BackupRecord, directory?: BackupDirectoryHandle) {
  if (!backup.file_name) throw new Error("The completed backup has no archive file.");
  const blob = await apiBlob(`/profiles/${profileId}/backups/${backup.id}/download`);
  if (directory) {
    const file = await directory.getFileHandle(backup.file_name, { create: true });
    const output = await file.createWritable();
    await output.write(blob);
    await output.close();
    return;
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = backup.file_name;
  link.click();
  URL.revokeObjectURL(url);
}

function draftFrom(policy: BackupPolicy): PolicyDraft {
  return {
    keep_count: policy.keep_count?.toString() ?? "",
    keep_days: policy.keep_days?.toString() ?? "",
    max_total_mb: policy.max_total_mb?.toString() ?? "",
    redundancy_enabled: policy.redundancy_enabled,
    destinations: policy.destinations,
  };
}

function parseRule(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

function BackupGuide({ close }: { close: () => void }) {
  return <aside className="workspace-guide backup-guide" id="backup-guide" aria-labelledby="backup-guide-title">
    <div className="workspace-guide__heading">
      <div>
        <p className="eyebrow">Protection guide</p>
        <h3 id="backup-guide-title">From live world to safe restore</h3>
      </div>
      <Button className="button--quiet button--small" onClick={close}>Close guide</Button>
    </div>
    <ol className="workspace-guide__steps workspace-guide__steps--three">
      <li><span>1</span><div><strong>Create a consistent snapshot</strong><small>If Minecraft is running, Blockstead briefly flushes and pauses saving while it archives every world folder.</small></div></li>
      <li><span>2</span><div><strong>Verify before trusting</strong><small>The completed archive gets a manifest and SHA-256 checksum. You can also save a portable copy to a folder you choose.</small></div></li>
      <li><span>3</span><div><strong>Preview before restoring</strong><small>Blockstead checks the archive, disk space, and affected worlds first, then preserves today’s folders beside the restored ones.</small></div></li>
    </ol>
    <p className="workspace-guide__note"><strong>The safety net:</strong> Retention never removes the newest completed backup. Scheduled backups appear in the same history as manual ones.</p>
  </aside>;
}

export function BackupsPanel({
  profileId,
  running,
  serverState,
}: {
  profileId: string;
  running: boolean;
  serverState?: ProcessState["state"];
}) {
  const cache = useQueryClient();
  const restoreReview = useRef<HTMLDivElement>(null);
  const restoreTrigger = useRef<HTMLButtonElement | null>(null);
  const guideTrigger = useRef<HTMLButtonElement>(null);
  const [restoreTarget, setRestoreTarget] = useState<BackupRecord | null>(null);
  const [exportNotice, setExportNotice] = useState("");
  const [exportError, setExportError] = useState("");
  const [policyDraft, setPolicyDraft] = useState<PolicyDraft | null>(null);
  const [destinationInput, setDestinationInput] = useState("");
  const [guideOpen, setGuideOpen] = useState(false);
  const [historyFilter, setHistoryFilter] = useState<"all" | "available" | "attention">("all");

  const backups = useQuery({
    queryKey: ["backups", profileId],
    queryFn: () => api<BackupRecord[]>(`/profiles/${profileId}/backups`),
    refetchInterval: query => query.state.data?.some(entry => entry.status === "in_progress") ? 1000 : false,
  });
  const policy = useQuery({
    queryKey: ["backup-policy", profileId],
    queryFn: () => api<BackupPolicy>(`/profiles/${profileId}/backup-policy`),
  });
  const create = useMutation({
    mutationFn: () => api<BackupRecord>(`/profiles/${profileId}/backups`, { method: "POST" }),
    onMutate: () => { setExportNotice(""); setExportError(""); },
    onSuccess: () => {
      setExportNotice("Backup completed and verified in Blockstead. Use Save a copy when you want a portable archive elsewhere.");
      void cache.invalidateQueries({ queryKey: ["backups", profileId] });
    },
    onError: () => void cache.invalidateQueries({ queryKey: ["backups", profileId] }),
  });
  const preview = useQuery({
    queryKey: ["restore-preview", profileId, restoreTarget?.id],
    queryFn: () => api<RestorePreview>(`/profiles/${profileId}/backups/${restoreTarget?.id}/restore-preview`),
    enabled: restoreTarget != null,
    retry: false,
    staleTime: 0,
  });
  const restore = useMutation({
    mutationFn: (backupId: string) => api<RestoreResult>(`/profiles/${profileId}/backups/${backupId}/restore`, { method: "POST" }),
    onSuccess: () => {
      closeRestoreReview();
      void cache.invalidateQueries({ queryKey: ["backups", profileId] });
    },
  });
  const savePolicy = useMutation({
    mutationFn: (next: BackupPolicy) => api<BackupPolicy & { expired_now: number }>(`/profiles/${profileId}/backup-policy`, { method: "PUT", body: JSON.stringify(next) }),
    onSuccess: () => {
      setPolicyDraft(null);
      void cache.invalidateQueries({ queryKey: ["backup-policy", profileId] });
      void cache.invalidateQueries({ queryKey: ["backups", profileId] });
    },
  });

  useEffect(() => {
    if (restoreTarget) restoreReview.current?.focus();
  }, [restoreTarget]);

  function closeRestoreReview() {
    setRestoreTarget(null);
    requestAnimationFrame(() => restoreTrigger.current?.focus());
  }

  function closeGuide() {
    setGuideOpen(false);
    requestAnimationFrame(() => guideTrigger.current?.focus());
  }

  const records = backups.data ?? [];
  const availableRecords = records.filter(entry => entry.status === "completed" && entry.archive_available);
  const attentionRecords = records.filter(entry => entry.status === "failed" || entry.status === "expired" || (entry.status === "completed" && !entry.archive_available));
  const visibleRecords = historyFilter === "available" ? availableRecords : historyFilter === "attention" ? attentionRecords : records;
  const lastSuccess = availableRecords[0];
  const inProgress = records.find(entry => entry.status === "in_progress");
  const storedBytes = availableRecords.reduce((total, entry) => total + (entry.size_bytes ?? 0), 0);
  const historyReady = backups.data != null;
  const draft = policyDraft ?? (policy.data ? draftFrom(policy.data) : null);
  const editRule = (rule: "keep_count" | "keep_days" | "max_total_mb") => (value: string) => {
    if (draft) setPolicyDraft({ ...draft, [rule]: value });
  };
  const effectiveState = serverState ?? (running ? "RUNNING" : "STOPPED");
  const changingState = effectiveState === "STARTING" || effectiveState === "STOPPING";
  const liveWorld = running || effectiveState === "STARTING" || effectiveState === "DEGRADED";
  const createLocked = create.isPending || restore.isPending || Boolean(inProgress) || changingState;

  const policyPayload = (): BackupPolicy | null => draft ? {
    keep_count: parseRule(draft.keep_count),
    keep_days: parseRule(draft.keep_days),
    max_total_mb: parseRule(draft.max_total_mb),
    redundancy_enabled: draft.redundancy_enabled,
    destinations: draft.destinations,
  } : null;

  return <section className="card backups backups-workspace" id="backups">
    <header className="workspace-hero workspace-hero--backups">
      <div className="workspace-hero__copy">
        <p className="eyebrow">World protection</p>
        <div className="workspace-hero__title">
          <span className="workspace-hero__icon"><NavIcon name="package" /></span>
          <h2>Backup Center</h2>
        </div>
        <p>Keep a verified history of your world, save portable copies, and review every restore before a single folder changes.</p>
        <div className="workspace-hero__actions">
          <Button ref={guideTrigger} className="button--light button--small" aria-expanded={guideOpen} aria-controls="backup-guide" onClick={() => guideOpen ? closeGuide() : setGuideOpen(true)}>
            {guideOpen ? "Hide backup guide" : "Open backup guide"}
          </Button>
          <span className={`workspace-state${lastSuccess ? " workspace-state--ready" : " workspace-state--locked"}`}>
            <i aria-hidden="true" />{!historyReady ? backups.error ? "Protection unknown" : "Checking protection" : lastSuccess ? "World protected" : "First backup needed"}
          </span>
        </div>
      </div>
      <div className="workspace-stats" aria-label="Recent backup summary">
        <article><span>Last protected</span><strong>{!historyReady ? "—" : lastSuccess ? formatWhen(lastSuccess.created_at) : "Not yet"}</strong><small>{!historyReady ? "checking history" : lastSuccess ? "verified archive" : "create your first copy"}</small></article>
        <article><span>Recent copies</span><strong>{historyReady ? availableRecords.length : "—"}</strong><small>{!historyReady ? "checking history" : storedBytes ? formatBytes(storedBytes) : "nothing stored"}</small></article>
        <article><span>Retention</span><strong>{policy.data?.keep_count ?? "—"}</strong><small>{retentionSummary(policy.data)}</small></article>
      </div>
    </header>

    {guideOpen && <BackupGuide close={closeGuide} />}

    <nav className="workspace-jump" aria-label="Backup Center sections">
      <a href="#create-backup"><span>01</span><strong>Protect now</strong><small>Create a verified copy</small></a>
      <a href="#backup-history"><span>02</span><strong>History</strong><small>Review and restore</small></a>
      <a href="#backup-settings"><span>03</span><strong>Storage rules</strong><small>Retention and mirrors</small></a>
    </nav>

    {inProgress && <div className="backup-progress" role="status" aria-live="polite">
      <span className="backup-progress__pulse" aria-hidden="true" />
      <div><strong>Backup in progress</strong><p>Minecraft’s world is being archived. History refreshes automatically when it finishes.</p></div>
    </div>}

    <section className="backup-action" id="create-backup" aria-labelledby="create-backup-heading">
      <span className="backup-action__icon" aria-hidden="true"><NavIcon name="package" /></span>
      <div>
        <div className="heading-with-help">
          <h3 id="create-backup-heading">Create a fresh world backup</h3>
          <Tooltip label="Can I back up while players are online?">Yes. Blockstead briefly pauses saving, flushes the world to disk, creates the archive, and turns saving back on. Players may notice a short pause.</Tooltip>
        </div>
        <p>Blockstead keeps a private verified archive. Save a portable copy from history whenever you want one elsewhere.</p>
        <small>{changingState
          ? "Wait for the server to finish starting or stopping before beginning."
          : liveWorld
            ? "The live world will briefly pause saving, flush to disk, and resume automatically."
            : "This server is stopped, so its world can be archived directly."}</small>
      </div>
      <div className="backup-action__cta">
        <Button disabled={createLocked} onClick={() => create.mutate()}>{create.isPending ? "Backing up…" : inProgress ? "Backup in progress" : changingState ? "Wait for server" : "Back up now"}</Button>
        <small>No folder choice is needed; Blockstead stores this restore point privately.</small>
      </div>
    </section>

    {create.error && <p className="error" role="alert">{create.error.message}</p>}
    {exportNotice && <p className="success" role="status">{exportNotice}</p>}
    {exportError && <p className="error" role="alert">{exportError}</p>}
    {restore.isSuccess && restore.data && <p className="success" role="status">
      {restore.data.result}{restore.data.preserved_paths.length > 0 && ` Previous folders: ${restore.data.preserved_paths.join(", ")}.`}
    </p>}

    {restoreTarget && <div className="restore-review" role="region" aria-label="Restore review" ref={restoreReview} tabIndex={-1}>
      <div className="restore-review__heading">
        <div><p className="eyebrow">Safety review</p><h3>Restore {formatWhen(restoreTarget.created_at)}</h3></div>
        <Button className="button--quiet button--small" disabled={restore.isPending} onClick={closeRestoreReview}>Cancel restore</Button>
      </div>
      {preview.isLoading && <div className="restore-review__loading" role="status"><span aria-hidden="true" /><p>Verifying the archive checksum and available disk space…</p></div>}
      {preview.error && <div className="restore-review__error">
        <p className="error" role="alert">{preview.error.message}</p>
        <Button className="button--secondary button--small" onClick={() => void preview.refetch()}>Try verification again</Button>
      </div>}
      {preview.data && <>
        <p>The archive passed checksum verification. Review exactly what will happen before restoring it.</p>
        <ul className="restore-checks">
          <li className="restore-checks__ok"><span aria-hidden="true">✓</span><div><strong>Archive verified</strong><small>{formatBytes(preview.data.size_bytes)} · SHA-256 {preview.data.sha256.slice(0, 12)}…</small></div></li>
          <li className={preview.data.available_bytes >= preview.data.required_bytes ? "restore-checks__ok" : "restore-checks__blocked"}><span aria-hidden="true">{preview.data.available_bytes >= preview.data.required_bytes ? "✓" : "!"}</span><div><strong>Disk space checked</strong><small>{formatBytes(preview.data.available_bytes)} available · {formatBytes(preview.data.required_bytes)} needed</small></div></li>
          <li className="restore-checks__ok"><span aria-hidden="true">✓</span><div><strong>Current world preserved</strong><small>{preview.data.worlds_replaced.length ? preview.data.worlds_replaced.join(", ") : "No existing world folders will be replaced"}</small></div></li>
        </ul>
        <div className="restore-impact">
          <div><span>Backup contains</span><strong>{preview.data.included_paths.join(", ") || "No world paths"}</strong></div>
          <div><span>Minecraft</span><strong>{preview.data.minecraft_version ?? "Version not recorded"}</strong></div>
        </div>
        <p className="restore-preserve-note">The current world folders are kept beside the restored ones until you choose to remove them.</p>
        {preview.data.blockers.length > 0 && <ul className="restore-blockers">
          {preview.data.blockers.map(blocker => <li key={blocker} className="error"><span aria-hidden="true">!</span>{blocker}</li>)}
        </ul>}
        <div className="restore-review__actions">
          <Button className="button--danger" disabled={!preview.data.can_restore || restore.isPending} onClick={() => restore.mutate(restoreTarget.id)}>{restore.isPending ? "Restoring…" : "Restore this backup"}</Button>
          <small>{preview.data.can_restore ? "This replaces the active world folders after preserving them." : "Resolve the items above before restoring."}</small>
        </div>
      </>}
      {restore.error && <p className="error" role="alert">{restore.error.message}</p>}
    </div>}

    <section className="backup-history" id="backup-history" aria-labelledby="backup-history-heading">
      <div className="workspace-section__heading">
        <div>
          <p className="eyebrow">Restore points</p>
          <div className="heading-with-help">
            <h3 id="backup-history-heading">Backup history</h3>
            <Tooltip label="What makes a backup verified?">Completed archives include a manifest and SHA-256 checksum. Blockstead checks that checksum again before it allows a restore.</Tooltip>
          </div>
          <p>The most recent 50 manual and scheduled attempts for this server.</p>
        </div>
        {records.length > 0 && <span className="section-count">{records.length} recent</span>}
      </div>

      {records.length > 0 && <div className="history-filter" role="group" aria-label="Filter backup history">
        <button type="button" className={historyFilter === "all" ? "active" : ""} aria-pressed={historyFilter === "all"} onClick={() => setHistoryFilter("all")}>All <span>{records.length}</span></button>
        <button type="button" className={historyFilter === "available" ? "active" : ""} aria-pressed={historyFilter === "available"} onClick={() => setHistoryFilter("available")}>Available <span>{availableRecords.length}</span></button>
        <button type="button" className={historyFilter === "attention" ? "active" : ""} aria-pressed={historyFilter === "attention"} onClick={() => setHistoryFilter("attention")}>Needs attention <span>{attentionRecords.length}</span></button>
      </div>}

      {backups.isLoading ? <p className="empty-note">Loading backup history…</p>
        : backups.error ? <div className="query-error"><p className="error" role="alert">{backups.error.message}</p><Button className="button--secondary button--small" onClick={() => void backups.refetch()}>Try loading history again</Button></div>
          : records.length === 0 ? <div className="backup-empty"><span aria-hidden="true"><NavIcon name="package" /></span><h4>Your first restore point will appear here</h4><p>No backups have been attempted for this server yet.</p></div>
            : visibleRecords.length === 0 ? <div className="backup-empty backup-empty--small"><h4>No backups in this view</h4><p>Choose another filter to see the rest of your history.</p></div>
              : <ol className="backup-list">
                {visibleRecords.map((record, index) => <li key={record.id} className={`backup-record${index === 0 && historyFilter === "all" ? " backup-record--newest" : ""}`}>
                  <span className={`backup-record__rail backup-record__rail--${record.status}${record.status === "completed" && !record.archive_available ? " backup-record__rail--missing" : ""}`} aria-hidden="true" />
                  <div className="backup-record__main">
                    <div className="backup-record__heading">
                      <div><strong>{formatWhen(record.created_at)}</strong>{index === 0 && historyFilter === "all" && <span className="backup-record__newest">Newest</span>}</div>
                      <span className={`backup-status backup-status--${record.status}${record.status === "completed" && !record.archive_available ? " backup-status--missing" : ""}`}>{statusLabel(record)}</span>
                    </div>
                    <p>{record.result}</p>
                    {record.status === "completed" && record.sha256 && <details className="backup-integrity"><summary>Verified archive details</summary><code>SHA-256 {record.sha256}</code>{record.file_name && <small>{record.file_name}</small>}</details>}
                  </div>
                  <dl className="backup-record__facts">
                    <div><dt>Created by</dt><dd>{record.trigger === "schedule" ? "Schedule" : "Manual"}</dd></div>
                    <div><dt>Size</dt><dd>{record.size_bytes == null ? "—" : formatBytes(record.size_bytes)}</dd></div>
                    <div><dt>Duration</dt><dd>{formatDuration(record.duration_ms)}</dd></div>
                  </dl>
                  <div className="backup-record__actions">
                    {record.status === "completed" && record.archive_available ? <>
                      <Button className="button--secondary button--small" aria-label={`Restore backup from ${formatWhen(record.created_at)}`} disabled={restore.isPending} onClick={event => { if (restore.isPending) return; restoreTrigger.current = event.currentTarget; restore.reset(); setRestoreTarget(record); }}>Restore…</Button>
                      <Button className="button--quiet button--small" aria-label={`Save a copy of backup from ${formatWhen(record.created_at)}`} onClick={() => {
                        const picker = directoryPicker();
                        setExportNotice("");
                        setExportError("");
                        void (async () => {
                          try {
                            const directory = picker ? await picker() : undefined;
                            await saveBackup(profileId, record, directory);
                            setExportNotice(directory ? "Backup copy saved to the selected folder." : "Your browser downloaded a backup copy.");
                          } catch (error) {
                            if (isAbortError(error)) return;
                            setExportError(error instanceof Error ? error.message : "The backup could not be saved.");
                          }
                        })();
                      }}>Save a copy…</Button>
                    </> : record.status === "completed" && !record.archive_available ? <small>The retained archive is no longer available.</small> : null}
                  </div>
                </li>)}
              </ol>}
    </section>

    <section className="backup-policy" id="backup-settings" aria-labelledby="retention-heading">
      <div className="workspace-section__heading">
        <div>
          <p className="eyebrow">Storage housekeeping</p>
          <div className="heading-with-help">
            <h3 id="retention-heading">Retention and extra copies</h3>
            <Tooltip label="How backup retention works">Limits are checked together after a successful backup. Blockstead always preserves the newest completed backup, even when a limit would otherwise remove it.</Tooltip>
          </div>
          <p>{retentionSummary(policy.data)}. Leave a rule blank for no limit.</p>
        </div>
        {policy.data && <span className={`policy-state${policy.data.redundancy_enabled ? " policy-state--on" : ""}`}>{policy.data.redundancy_enabled ? `${policy.data.destinations.length} mirror${policy.data.destinations.length === 1 ? "" : "s"}` : "Local only"}</span>}
      </div>

      {policy.isLoading && <p className="empty-note">Loading backup settings…</p>}
      {policy.error && <div className="query-error"><p className="error" role="alert">{policy.error.message}</p><Button className="button--secondary button--small" onClick={() => void policy.refetch()}>Try loading settings again</Button></div>}
      {draft && <form className="backup-policy__form" onSubmit={event => {
        event.preventDefault();
        const next = policyPayload();
        if (next) savePolicy.mutate(next);
      }}>
        <div className="retention-rules">
          <label><span>Maximum copies</span><div><input aria-label="Keep at most backups" type="number" min={1} max={500} value={draft.keep_count} onChange={event => editRule("keep_count")(event.target.value)} /><strong>backups</strong></div><small>Oldest copies leave first.</small></label>
          <label><span>Maximum age</span><div><input aria-label="Keep backups for days" type="number" min={1} max={3650} value={draft.keep_days} onChange={event => editRule("keep_days")(event.target.value)} /><strong>days</strong></div><small>Based on creation time.</small></label>
          <label><span>Storage budget</span><div><input aria-label="Use at most megabytes" type="number" min={100} max={10000000} value={draft.max_total_mb} onChange={event => editRule("max_total_mb")(event.target.value)} /><strong>MB</strong></div><small>Counts retained archives here.</small></label>
        </div>

        <p className="retention-warning"><span aria-hidden="true">◆</span> Saving tighter limits can expire older Blockstead archives immediately. The newest completed backup is always kept.</p>

        <details className="backup-copies">
          <summary><span><strong>Copies on another drive</strong><small>Optional protection outside Blockstead’s private storage</small></span><i>{draft.redundancy_enabled ? "On" : "Off"}</i></summary>
          <div className="backup-copies__body">
            <div className="heading-with-help"><h4>Mirror every successful backup</h4><Tooltip label="What counts as an approved destination">Enter an existing absolute folder path on the computer running Blockstead. In Docker, mount the folder first and use its container path. Up to eight destinations are supported.</Tooltip></div>
            <p>Manual and scheduled archives are copied to each approved host folder. Retention removes Blockstead’s primary archives but does not prune these mirrored copies.</p>
            <label className="check-label"><input type="checkbox" checked={draft.redundancy_enabled} onChange={event => setPolicyDraft({ ...draft, redundancy_enabled: event.target.checked })} /> Mirror every backup to approved folders</label>
            <div className="inline-form"><label>Destination folder<input value={destinationInput} onChange={event => setDestinationInput(event.target.value)} placeholder="/media/backup-drive/minecraft" /></label><Button type="button" className="button--secondary" disabled={!destinationInput.trim() || draft.destinations.length >= 8} onClick={() => {
              const value = destinationInput.trim();
              if (!draft.destinations.includes(value) && draft.destinations.length < 8) setPolicyDraft({ ...draft, destinations: [...draft.destinations, value] });
              setDestinationInput("");
            }}>Add folder</Button></div>
            <small className="destination-limit">{draft.destinations.length} of 8 approved destinations</small>
            {draft.destinations.length > 0 ? <ul className="destination-list">{draft.destinations.map(destination => <li key={destination}><code>{destination}</code><Button type="button" className="button--quiet button--small" aria-label={`Remove destination ${destination}`} onClick={() => setPolicyDraft({ ...draft, destinations: draft.destinations.filter(value => value !== destination) })}>Remove</Button></li>)}</ul> : <p className="empty-note">No additional destinations approved.</p>}
          </div>
        </details>

        <div className="backup-policy__actions">
          <Button className="button--secondary" type="submit" disabled={savePolicy.isPending || policyDraft == null}>{savePolicy.isPending ? "Saving…" : "Save backup settings"}</Button>
          {policyDraft == null && <small>Change a rule or destination to enable saving.</small>}
        </div>
      </form>}
      {savePolicy.error && <p className="error" role="alert">{savePolicy.error.message}</p>}
      {savePolicy.isSuccess && <p className="success" role="status">Retention saved.{savePolicy.data.expired_now > 0 && ` ${savePolicy.data.expired_now} older backup${savePolicy.data.expired_now === 1 ? "" : "s"} removed.`}</p>}
    </section>
  </section>;
}
