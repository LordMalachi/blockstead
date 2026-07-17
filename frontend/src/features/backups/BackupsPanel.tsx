import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BackupRecord } from "../../api/client";
import { Button } from "../../components/Button";
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

export function BackupsPanel({ profileId, running }: { profileId: string; running: boolean }) {
  const cache = useQueryClient();
  const backups = useQuery({
    queryKey: ["backups", profileId],
    queryFn: () => api<BackupRecord[]>(`/profiles/${profileId}/backups`),
    refetchInterval: query => query.state.data?.some(entry => entry.status === "in_progress") ? 1000 : false,
  });
  const create = useMutation({
    mutationFn: () => api<BackupRecord>(`/profiles/${profileId}/backups`, { method: "POST" }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["backups", profileId] }),
    onError: () => void cache.invalidateQueries({ queryKey: ["backups", profileId] }),
  });
  const records = backups.data ?? [];
  const lastSuccess = records.find(entry => entry.status === "completed");

  return <section className="card backups" id="backups">
    <div className="section-heading">
      <div><p className="eyebrow">World protection</p><h2>Backup Center</h2></div>
      <span>{lastSuccess ? `Last protected ${formatWhen(lastSuccess.created_at)}` : "No successful backup yet"}</span>
    </div>
    <div className="backup-action">
      <div>
        <h3>Create a world backup</h3>
        <p>Blockstead stores a private compressed archive of every world folder for this server.</p>
        <small>{running ? "The server will briefly pause saving, flush the world, create the archive, and immediately turn saving back on." : "This server is stopped, so its world can be archived directly."}</small>
      </div>
      <Button disabled={create.isPending} onClick={() => create.mutate()}>{create.isPending ? "Backing up…" : "Back up now"}</Button>
    </div>
    {create.error && <p className="error" role="alert">{create.error.message}</p>}
    {create.isSuccess && <p className="success" role="status">Backup completed successfully.</p>}
    <div className="backup-history">
      <h3>Backup history</h3>
      {backups.isLoading ? <p className="empty-note">Loading backup history…</p> : records.length === 0 ? <p className="empty-note">No backups have been attempted for this server yet.</p> : <div className="backup-table-wrap"><table className="backup-table">
        <thead><tr><th scope="col">Created</th><th scope="col">Status</th><th scope="col">Source</th><th scope="col">Size</th><th scope="col">Duration</th><th scope="col">Result</th></tr></thead>
        <tbody>{records.map(record => <tr key={record.id}>
          <td>{formatWhen(record.created_at)}</td>
          <td><span className={`backup-status backup-status--${record.status}`}>{record.status.replace("_", " ")}</span></td>
          <td>{record.trigger === "schedule" ? "Schedule" : "Manual"}</td>
          <td>{record.size_bytes == null ? "—" : formatBytes(record.size_bytes)}</td>
          <td>{formatDuration(record.duration_ms)}</td>
          <td>{record.result}</td>
        </tr>)}</tbody>
      </table></div>}
    </div>
    <p className="muted-note">Restore previews, retention rules, and checksum verification are coming in the next Backup Center slices.</p>
  </section>;
}
