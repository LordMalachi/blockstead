import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type BackupPolicy, type BackupRecord, type RestorePreview, type RestoreResult } from "../../api/client";
import { Button } from "../../components/Button";
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

interface PolicyDraft { keep_count: string; keep_days: string; max_total_mb: string }

function draftFrom(policy: BackupPolicy): PolicyDraft {
  return {
    keep_count: policy.keep_count?.toString() ?? "",
    keep_days: policy.keep_days?.toString() ?? "",
    max_total_mb: policy.max_total_mb?.toString() ?? "",
  };
}

function parseRule(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

export function BackupsPanel({ profileId, running }: { profileId: string; running: boolean }) {
  const cache = useQueryClient();
  const [restoreTarget, setRestoreTarget] = useState<BackupRecord | null>(null);
  const [policyDraft, setPolicyDraft] = useState<PolicyDraft | null>(null);
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
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["backups", profileId] }),
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
      setRestoreTarget(null);
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
  const records = backups.data ?? [];
  const lastSuccess = records.find(entry => entry.status === "completed");
  const draft = policyDraft ?? (policy.data ? draftFrom(policy.data) : null);
  const editRule = (rule: keyof PolicyDraft) => (value: string) => {
    if (draft) setPolicyDraft({ ...draft, [rule]: value });
  };

  return <section className="card backups" id="backups">
    <div className="section-heading">
      <div><p className="eyebrow">World protection</p><h2>Backup Center</h2></div>
      <span>{lastSuccess ? `Last protected ${formatWhen(lastSuccess.created_at)}` : "No successful backup yet"}</span>
    </div>
    <div className="backup-action">
      <div>
        <h3>Create a world backup</h3>
        <p>Blockstead stores a private compressed archive of every world folder for this server, with a manifest and SHA-256 checksum for later verification.</p>
        <small>{running ? "The server will briefly pause saving, flush the world, create the archive, and immediately turn saving back on." : "This server is stopped, so its world can be archived directly."}</small>
      </div>
      <Button disabled={create.isPending} onClick={() => create.mutate()}>{create.isPending ? "Backing up…" : "Back up now"}</Button>
    </div>
    {create.error && <p className="error" role="alert">{create.error.message}</p>}
    {create.isSuccess && <p className="success" role="status">Backup completed successfully.</p>}
    {restore.isSuccess && restore.data && <p className="success" role="status">
      {restore.data.result}{restore.data.preserved_paths.length > 0 && ` Previous folders: ${restore.data.preserved_paths.join(", ")}.`}
    </p>}
    {restoreTarget && <div className="restore-review" role="region" aria-label="Restore review">
      <h3>Restore the backup from {formatWhen(restoreTarget.created_at)}</h3>
      {preview.isLoading && <p>Verifying the archive checksum…</p>}
      {preview.error && <p className="error" role="alert">{preview.error.message}</p>}
      {preview.data && <>
        <p>
          The archive passed checksum verification. Restoring will replace
          {" "}<strong>{preview.data.worlds_replaced.join(", ") || "no existing folders"}</strong> with
          the backup's {preview.data.included_paths.join(", ")} ({formatBytes(preview.data.size_bytes)}).
          The current world folders are kept beside the restored ones until you remove them.
        </p>
        {preview.data.blockers.length > 0 && <ul className="restore-blockers">
          {preview.data.blockers.map(blocker => <li key={blocker} className="error">{blocker}</li>)}
        </ul>}
        <div className="restore-review__actions">
          <Button
            className="button--danger"
            disabled={!preview.data.can_restore || restore.isPending}
            onClick={() => restore.mutate(restoreTarget.id)}
          >{restore.isPending ? "Restoring…" : "Restore this backup"}</Button>
          <Button className="button--secondary" onClick={() => setRestoreTarget(null)}>Cancel</Button>
        </div>
      </>}
      {restore.error && <p className="error" role="alert">{restore.error.message}</p>}
    </div>}
    <div className="backup-history">
      <h3>Backup history</h3>
      {backups.isLoading ? <p className="empty-note">Loading backup history…</p> : records.length === 0 ? <p className="empty-note">No backups have been attempted for this server yet.</p> : <div className="backup-table-wrap"><table className="backup-table">
        <thead><tr><th scope="col">Created</th><th scope="col">Status</th><th scope="col">Source</th><th scope="col">Size</th><th scope="col">Duration</th><th scope="col">Result</th><th scope="col"><span className="visually-hidden">Actions</span></th></tr></thead>
        <tbody>{records.map(record => <tr key={record.id}>
          <td>{formatWhen(record.created_at)}</td>
          <td><span className={`backup-status backup-status--${record.status}`} title={record.sha256 ? `SHA-256 ${record.sha256}` : undefined}>{record.status.replace("_", " ")}</span></td>
          <td>{record.trigger === "schedule" ? "Schedule" : "Manual"}</td>
          <td>{record.size_bytes == null ? "—" : formatBytes(record.size_bytes)}</td>
          <td>{formatDuration(record.duration_ms)}</td>
          <td>{record.result}</td>
          <td>{record.status === "completed" && record.archive_available && <Button className="button--secondary button--small" onClick={() => { restore.reset(); setRestoreTarget(record); }}>Restore…</Button>}</td>
        </tr>)}</tbody>
      </table></div>}
    </div>
    <div className="backup-policy">
      <div className="heading-with-help"><h3>Retention</h3><Tooltip label="How backup retention works">Limits are checked after a successful backup. Blockstead always preserves the newest completed backup, even when a limit would otherwise remove it.</Tooltip></div>
      <p>Older completed backups are removed by these rules after each new backup. The newest completed backup is always kept. Leave a rule blank for no limit.</p>
      {draft && <form className="backup-policy__form" onSubmit={event => {
        event.preventDefault();
        savePolicy.mutate({
          keep_count: parseRule(draft.keep_count),
          keep_days: parseRule(draft.keep_days),
          max_total_mb: parseRule(draft.max_total_mb),
        });
      }}>
        <label>Keep at most<input type="number" min={1} max={500} value={draft.keep_count} onChange={event => editRule("keep_count")(event.target.value)} /><span>backups</span></label>
        <label>Keep for<input type="number" min={1} max={3650} value={draft.keep_days} onChange={event => editRule("keep_days")(event.target.value)} /><span>days</span></label>
        <label>Use at most<input type="number" min={100} max={10000000} value={draft.max_total_mb} onChange={event => editRule("max_total_mb")(event.target.value)} /><span>MB</span></label>
        <Button className="button--secondary" type="submit" disabled={savePolicy.isPending || policyDraft == null}>{savePolicy.isPending ? "Saving…" : "Save retention"}</Button>
      </form>}
      {savePolicy.error && <p className="error" role="alert">{savePolicy.error.message}</p>}
      {savePolicy.isSuccess && <p className="success" role="status">
        Retention saved.{savePolicy.data.expired_now > 0 && ` ${savePolicy.data.expired_now} older backup${savePolicy.data.expired_now === 1 ? "" : "s"} removed.`}
      </p>}
    </div>
  </section>;
}
