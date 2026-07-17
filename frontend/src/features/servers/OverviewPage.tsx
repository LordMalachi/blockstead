import { useQuery } from "@tanstack/react-query";
import { api, type BackupRecord } from "../../api/client";
import { PrerequisitesPanel } from "../extensions/PrerequisitesPanel";
import { useServerScope } from "./scope";

const STALE_AFTER_DAYS = 7;

function protection(records: BackupRecord[] | undefined): { value: string; note: string; warn: boolean } {
  if (records === undefined) return { value: "…", note: "Checking backup history", warn: false };
  const last = records.find(record => record.status === "completed");
  if (!last) return { value: "Never", note: "Create a backup from the Backups page", warn: true };
  const ageDays = Math.floor((Date.now() - new Date(last.created_at).getTime()) / 86_400_000);
  const value = ageDays <= 0 ? "Today" : ageDays === 1 ? "Yesterday" : `${ageDays} days ago`;
  if (ageDays > STALE_AFTER_DAYS) {
    return { value, note: "Consider a fresh backup from the Backups page", warn: true };
  }
  return { value, note: last.archive_available ? "Verified archive is ready to restore" : "Latest archive is no longer on disk", warn: !last.archive_available };
}

export function OverviewPage() {
  const scope = useServerScope();
  const backups = useQuery({
    queryKey: ["backups", scope.profile.id],
    queryFn: () => api<BackupRecord[]>(`/profiles/${scope.profile.id}/backups`),
  });
  const protected_ = protection(backups.data);
  return <>
    <section className="metrics" aria-label="Server summary">
      <article><span>Server state</span><strong>{scope.state}</strong><small>{scope.running ? "Accepting commands" : "Not using host resources"}</small></article>
      <article><span>Minecraft</span><strong>{scope.profile.minecraft_version ?? "—"}</strong><small>{scope.profile.distribution}</small></article>
      <article><span>Last backup</span><strong>{protected_.value}</strong><small className={protected_.warn ? "metric-warning" : undefined}>{protected_.note}</small></article>
      <article><span>Process ID</span><strong>{scope.pid ?? "—"}</strong><small>{scope.pid ? "Managed by Blockstead" : "No active process"}</small></article>
      <article><span>Last exit</span><strong>{scope.exitCode ?? "—"}</strong><small>{scope.exitCode == null ? "No exit recorded" : scope.exitCode === 0 ? "Clean shutdown" : "Needs attention"}</small></article>
    </section>
    <PrerequisitesPanel profileId={scope.profile.id} />
  </>;
}
