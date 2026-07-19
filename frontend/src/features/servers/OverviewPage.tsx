import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type OverviewMetricPoint, type ProfileOverview } from "../../api/client";
import { Button } from "../../components/Button";
import { formatBytes, formatUptime } from "../../lib/format";
import { PrerequisitesPanel } from "../extensions/PrerequisitesPanel";
import { useServerScope } from "./scope";

function relativeDate(value: string): string {
  const date = new Date(value);
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function operationTime(value: string): string {
  const date = new Date(value);
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const day = date.toDateString() === new Date().toDateString()
    ? "Today"
    : date.toDateString() === tomorrow.toDateString() ? "Tomorrow" : date.toLocaleDateString(undefined, { weekday: "short" });
  return `${day} at ${date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
}

function Sparkline({ values, label, percent = false }: { values: Array<number | null>; label: string; percent?: boolean }) {
  const present = values.filter((value): value is number => value != null);
  if (!present.length) return <div className="sparkline sparkline--empty"><span>No samples yet</span></div>;
  const lower = percent ? 0 : Math.min(...present);
  const upperValue = percent ? 100 : Math.max(...present);
  const upper = upperValue === lower ? lower + 1 : upperValue;
  const points = present.map((value, index) => {
    const x = present.length === 1 ? 80 : index * (160 / (present.length - 1));
    const y = 42 - ((value - lower) / (upper - lower)) * 38;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return <svg className="sparkline" viewBox="0 0 160 44" role="img" aria-label={label} preserveAspectRatio="none"><path d="M0 42 H160" /><polyline points={points} /></svg>;
}

function HistoryCard({ label, value, note, points, field, percent = false }: {
  label: string;
  value: string;
  note: string;
  points: OverviewMetricPoint[];
  field: keyof OverviewMetricPoint;
  percent?: boolean;
}) {
  return <article className="health-card"><div><span>{label}</span><strong>{value}</strong><small>{note}</small></div><Sparkline values={points.map(point => typeof point[field] === "number" ? point[field] : null)} label={`${label} recent history`} percent={percent} /></article>;
}

export function OverviewPage() {
  const scope = useServerScope();
  const [copied, setCopied] = useState(false);
  const overview = useQuery({
    queryKey: ["overview", scope.profile.id],
    queryFn: () => api<ProfileOverview>(`/profiles/${scope.profile.id}/overview`),
    refetchInterval: 10_000,
  });
  const data = overview.data;

  async function copyAddress() {
    if (!data) return;
    await navigator.clipboard.writeText(data.join.address);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  if (!data) return <section className="card"><p className="empty-note">Building the server overview…</p>{overview.error && <p className="error">{overview.error.message}</p>}</section>;

  const current = data.metrics.current;
  const playerValue = data.players.online == null ? `— / ${data.players.max}` : `${data.players.online} / ${data.players.max}`;
  const backupNote = data.last_backup?.archive_available ? "Verified and ready to restore" : data.last_backup ? "Archive is no longer on disk" : "Create the first backup";

  return <>
    <section className="overview-summary" aria-label="Server summary">
      <article><span>Players online</span><strong>{playerValue}</strong><small>{data.players.available ? data.players.sample.length ? data.players.sample.join(", ") : "Server responded; nobody is online" : scope.running ? "Live status is not responding" : "Available when the server is running"}</small></article>
      <article><span>Uptime</span><strong>{data.state.uptime_seconds != null ? formatUptime(data.state.uptime_seconds) : "—"}</strong><small>{scope.running ? "Since this server started" : "Server is not running"}</small></article>
      <article><span>Last backup</span><strong>{data.last_backup ? relativeDate(data.last_backup.created_at) : "Never"}</strong><small className={!data.last_backup?.archive_available ? "metric-warning" : undefined}>{backupNote}</small></article>
      <article><span>Next operation</span><strong>{data.next_operation?.label ?? "None"}</strong><small>{data.next_operation ? operationTime(data.next_operation.at) : "No daily schedule is enabled"}</small></article>
    </section>

    <section className="join-card card" aria-labelledby="join-heading">
      <div><p className="eyebrow">Minecraft connection</p><h2 id="join-heading">Join this server</h2><p>Enter this address in Minecraft: Java Edition. The port is shown separately so it is easy to use in router or firewall settings.</p></div>
      <div className="join-address"><code>{data.join.host}</code><span>Port <strong>{data.join.port}</strong></span><Button className="button--secondary button--small" onClick={() => void copyAddress()}>{copied ? "Copied" : "Copy address"}</Button></div>
      <small>Full address: <code>{data.join.address}</code>. Blockstead does not open your firewall or router automatically.{data.join.candidate_hosts.length > 1 && ` Other detected host addresses: ${data.join.candidate_hosts.slice(1, 3).join(", ")}.`}</small>
    </section>

    <section className="card" aria-labelledby="health-heading">
      <div className="section-heading"><div><p className="eyebrow">Recent trends</p><h2 id="health-heading">Server and host health</h2></div><span>{data.metrics.history.length} sample{data.metrics.history.length === 1 ? "" : "s"}</span></div>
      <div className="health-grid">
        <HistoryCard label="Host CPU" value={`${current.cpu_percent.toFixed(0)}%`} note="Computer running Blockstead" points={data.metrics.history} field="cpu_percent" percent />
        <HistoryCard label="Host memory" value={`${current.memory_percent.toFixed(0)}%`} note={`${formatBytes(current.memory_used_bytes)} of ${formatBytes(current.memory_total_bytes)}`} points={data.metrics.history} field="memory_percent" percent />
        <HistoryCard label="Data disk" value={`${current.disk_percent.toFixed(0)}%`} note={`${formatBytes(current.disk_used_bytes)} of ${formatBytes(current.disk_total_bytes)}`} points={data.metrics.history} field="disk_percent" percent />
        <HistoryCard label="World size" value={current.world_size_bytes != null ? formatBytes(current.world_size_bytes) : "—"} note="Recognized world folders" points={data.metrics.history} field="world_size_bytes" />
      </div>
      <small className="muted-note">Blockstead keeps up to seven days of once-per-minute samples while a server is active. TPS and MSPT are omitted because this profile does not expose a reliable source.</small>
    </section>

    <div className="overview-columns">
      <section className="card overview-action-card" aria-labelledby="attention-heading">
        <div className="section-heading"><div><p className="eyebrow">Protection and readiness</p><h2 id="attention-heading">Needs attention</h2></div><span>{data.warnings.length || "Clear"}</span></div>
        {data.warnings.length ? <ul className="overview-list">{data.warnings.map(warning => <li key={warning.code} className={`overview-list__${warning.severity}`}><div><strong>{warning.title}</strong><p>{warning.detail}</p></div><Link to={warning.to}>Resolve</Link></li>)}</ul> : <p className="overview-clear">No readiness, crash, storage, or backup warnings right now.</p>}
      </section>

      <section className="card overview-activity" aria-labelledby="activity-heading">
        <div className="section-heading"><div><p className="eyebrow">Latest changes</p><h2 id="activity-heading">Recent activity</h2></div><span>{data.activity.length || "Quiet"}</span></div>
        {data.activity.length ? <ul className="overview-list">{data.activity.map(event => <li key={event.id}><div><strong>{event.category.replaceAll("_", " ")}</strong><p>{event.detail}</p><small>{new Date(event.created_at).toLocaleString()}</small></div><Link to={event.to}>View</Link></li>)}</ul> : <p className="overview-clear">No recent activity has been recorded for this server.</p>}
      </section>
    </div>

    <PrerequisitesPanel profileId={scope.profile.id} />

    <details className="card diagnostics">
      <summary>Diagnostics</summary>
      <p>Technical details for troubleshooting. Normal server care should not require these values.</p>
      <dl><div><dt>Process ID</dt><dd>{scope.pid ?? "—"}</dd></div><div><dt>Last exit code</dt><dd>{scope.exitCode ?? "—"}</dd></div><div><dt>Configured bind</dt><dd>{data.join.bind_address ?? "All interfaces"}</dd></div><div><dt>Process memory</dt><dd>{current.process_memory_bytes != null ? formatBytes(current.process_memory_bytes) : "—"}</dd></div><div><dt>Distribution</dt><dd>{data.capabilities.distribution_label}</dd></div></dl>
    </details>
  </>;
}
