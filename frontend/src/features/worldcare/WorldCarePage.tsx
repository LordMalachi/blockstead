import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type WorldCareView } from "../../api/client";
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
  const worldCare = useQuery({
    queryKey: ["world-care", scope.profile.id],
    queryFn: () => api<WorldCareView>(`/profiles/${scope.profile.id}/world-care`),
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
        <p>This workspace gathers storage and recovery facts. It does not remove files or recommend cleanup until Blockstead can show an exact, reviewed plan.</p>
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
        <div className="warning"><strong>Cleanup is not enabled</strong><span>{data.cleanup.detail}</span></div>
      </section>
    </div>

    <section className="card" aria-labelledby="destinations-heading">
      <div className="section-heading"><div><p className="eyebrow">Protection health</p><h2 id="destinations-heading">Backup destinations</h2></div><span>{data.backup_destinations.length} destination{data.backup_destinations.length === 1 ? "" : "s"}</span></div>
      <ul className="care-destinations">{data.backup_destinations.map((destination, index) => <li key={`${destination.configured_path}-${index}`}><div><strong>{destination.label}</strong><code>{destination.configured_path}</code></div><div><span>{bytes(destination.stored_bytes)} stored</span><small className={destination.disk.state === "available" ? "state-label state-label--ok" : "state-label state-label--warning"}>{destination.disk.state === "available" ? "Available" : destination.disk.state === "missing" ? "Not created" : "Could not check"}</small><small>{diskState(destination.disk)}</small></div></li>)}</ul>
    </section>
  </>;
}
