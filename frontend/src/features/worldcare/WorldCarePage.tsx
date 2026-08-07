import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type WorldCareView, type WorldCleanupPlan } from "../../api/client";
import { Button } from "../../components/Button";
import { formatBytes } from "../../lib/format";
import { useServerScope } from "../servers/scope";

function bytes(value: number | null): string {
  return value == null ? "Unknown" : formatBytes(value);
}

function diskState(value: WorldCareView["disk"]): string {
  if (value.state === "available" && value.free_bytes != null) {
    return `${bytes(value.free_bytes)} free · ${value.used_percent?.toFixed(0) ?? "—"}% used`;
  }
  if (value.state === "missing") return "Folder is not present yet";
  return "Could not check this filesystem";
}

export function WorldCarePage() {
  const scope = useServerScope();
  const client = useQueryClient();
  const worldCare = useQuery({
    queryKey: ["world-care", scope.profile.id],
    queryFn: () => api<WorldCareView>(`/profiles/${scope.profile.id}/world-care`),
  });
  const cleanupReview = useMutation({
    mutationFn: () => api<WorldCleanupPlan>(`/profiles/${scope.profile.id}/world-care/cleanup-plan`),
  });
  const applyCleanup = useMutation({
    mutationFn: (planId: string) => api<{ removed: number; result: string }>(`/profiles/${scope.profile.id}/world-care/cleanup-plan/${planId}/apply`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["world-care", scope.profile.id] }),
  });
  const destinationCheck = useMutation({
    mutationFn: () => api<{ destinations: unknown[] }>(`/profiles/${scope.profile.id}/backup-destinations/check`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["world-care", scope.profile.id] }),
  });
  const data = worldCare.data;

  if (!data) {
    return <section className="card"><p className="empty-note">Collecting world and recovery evidence…</p>{worldCare.error && <p className="error">{worldCare.error.message}</p>}</section>;
  }

  return <>
    <section className="page-head">
      <div>
        <p className="eyebrow">World Care</p>
        <h1>Protect the world before you change it</h1>
        <p>This workspace gathers storage and recovery facts. Cleanup is limited to an exact reviewed plan and never includes worlds, completed backups, or recovery copies.</p>
      </div>
    </section>

    <section className="workspace-stats world-care-stats" aria-label="World care summary">
      <article><span>Recognized world size</span><strong>{bytes(data.world_size_bytes)}</strong><small>{data.worlds.length} world folder{data.worlds.length === 1 ? "" : "s"}</small></article>
      <article><span>Server filesystem</span><strong>{data.disk.free_bytes == null ? "Unknown" : bytes(data.disk.free_bytes)}</strong><small>{diskState(data.disk)}</small></article>
      <article><span>Last verified backup</span><strong>{data.last_verified_backup ? "Ready" : "None"}</strong><small>{data.last_verified_backup ? `Recorded ${new Date(data.last_verified_backup.created_at).toLocaleDateString()}` : "Create a protection point before important changes"}</small></article>
      <article><span>Recovery copies</span><strong>{bytes(data.recovery.total_bytes)}</strong><small>Known local recovery artifacts</small></article>
    </section>

    <div className="world-care-columns">
      <section className="card" aria-labelledby="worlds-heading">
        <div className="section-heading"><div><p className="eyebrow">Observed folders</p><h2 id="worlds-heading">Worlds</h2></div><Link to={`/servers/${scope.profile.id}/files`}>Open Files</Link></div>
        {data.worlds.length ? <ul className="care-list">{data.worlds.map(world => <li key={world.name}><div><strong>{world.name}</strong><small>Recognized world folder</small></div><span>{bytes(world.size_bytes)}</span></li>)}</ul> : <p className="empty-note">No recognized world folder was found yet.</p>}
      </section>

      <section className="card" aria-labelledby="recovery-heading">
        <div className="section-heading"><div><p className="eyebrow">Reversible boundaries</p><h2 id="recovery-heading">Recovery storage</h2></div><Link to={`/servers/${scope.profile.id}/backups`}>Open Backups</Link></div>
        {data.recovery.entries.length ? <ul className="care-list">{data.recovery.entries.map(entry => <li key={entry.label}><div><strong>{entry.label}</strong><small>{entry.state === "available" ? "Measured on this computer" : "Measurement is incomplete"}</small></div><span>{bytes(entry.size_bytes)}</span></li>)}</ul> : <p className="empty-note">No retained recovery copies were found.</p>}
        <div className="warning"><strong>Reviewed cleanup only</strong><span>{data.cleanup.detail}</span></div>
        <div className="world-care-actions">
          <Button className="button--secondary button--small" disabled={cleanupReview.isPending || applyCleanup.isPending} onClick={() => cleanupReview.mutate()}>{cleanupReview.isPending ? "Reviewing…" : "Review cleanup"}</Button>
          <small>Review lists the exact private files and expires after 15 minutes.</small>
        </div>
        {cleanupReview.error && <p className="error" role="alert">{cleanupReview.error.message}</p>}
        {cleanupReview.data && <div className="world-care-cleanup" role="region" aria-label="Cleanup review">
          {cleanupReview.data.targets.length ? <>
            <p>Only these incomplete or expired private artifacts can be reclaimed.</p>
            <ul className="care-list">{cleanupReview.data.targets.map(target => <li key={target.path}><div><strong>{target.label}</strong><code>{target.path}</code><small>{target.reason} {target.recovery_effect}</small></div><span>{bytes(target.size_bytes)}</span></li>)}</ul>
          </> : <p className="empty-note">No incomplete or expired private artifact is eligible for cleanup.</p>}
          {cleanupReview.data.protected.length > 0 && <p className="muted-note">Protected from this plan: {cleanupReview.data.protected.map(item => item.label).join(", ")}.</p>}
          {cleanupReview.data.blockers.length > 0 && <ul className="restore-blockers">{cleanupReview.data.blockers.map(blocker => <li className="error" key={blocker}>{blocker}</li>)}</ul>}
          {cleanupReview.data.plan_id && <div className="world-care-actions"><Button className="button--danger button--small" disabled={!cleanupReview.data.can_apply || applyCleanup.isPending} onClick={() => { const planId = cleanupReview.data?.plan_id; if (planId) applyCleanup.mutate(planId); }}>{applyCleanup.isPending ? "Removing…" : "Remove reviewed artifacts"}</Button><small>This action rechecks every file before deletion.</small></div>}
          {applyCleanup.error && <p className="error" role="alert">{applyCleanup.error.message}</p>}
          {applyCleanup.data && <p className="success" role="status">{applyCleanup.data.result}</p>}
        </div>}
      </section>
    </div>

    <section className="card" aria-labelledby="destinations-heading">
      <div className="section-heading"><div><p className="eyebrow">Protection health</p><h2 id="destinations-heading">Backup destinations</h2></div><div className="world-care-actions"><Button className="button--secondary button--small" disabled={destinationCheck.isPending} onClick={() => destinationCheck.mutate()}>{destinationCheck.isPending ? "Checking…" : "Test resilience"}</Button><span>{data.backup_destinations.length} destination{data.backup_destinations.length === 1 ? "" : "s"}</span></div></div>
      <p className="muted-note">Tests write, read, and remove a private random file at each approved destination. No backup archive is changed.</p>
      {destinationCheck.error && <p className="error" role="alert">{destinationCheck.error.message}</p>}
      <ul className="care-destinations">{data.backup_destinations.map((destination, index) => <li key={`${destination.configured_path}-${index}`}><div><strong>{destination.label}</strong><code>{destination.configured_path}</code></div><div><span>{bytes(destination.stored_bytes)} stored</span><small className={destination.disk.state === "available" ? "state-label state-label--ok" : "state-label state-label--warning"}>{destination.disk.state === "available" ? "Available" : destination.disk.state === "missing" ? "Not created" : "Could not check"}</small><small>{diskState(destination.disk)}</small>{destination.last_check ? <small className={destination.last_check.state === "available" ? "state-label state-label--ok" : "state-label state-label--warning"}>{destination.last_check.state === "available" ? `Read/write verified ${new Date(destination.last_check.checked_at).toLocaleString()}` : destination.last_check.detail}</small> : <small>Not tested yet</small>}</div></li>)}</ul>
    </section>
  </>;
}
