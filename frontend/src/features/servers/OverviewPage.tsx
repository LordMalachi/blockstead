import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type DailySummaryFact, type DiagnosticCapture, type OverviewMetricPoint, type ProfileOverview } from "../../api/client";
import { Button } from "../../components/Button";
import { Tooltip } from "../../components/Tooltip";
import { formatBytes } from "../../lib/format";
import { PrerequisitesPanel } from "../extensions/PrerequisitesPanel";
import { useServerScope } from "./scope";
import { useRole } from "../shell/role";
import { serverSoftwareLabel, serverSoftwareVersion } from "./server-version";

function sampledTime(value: string | null): string {
  return value ? new Date(value).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) : "not yet sampled";
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

function DailyFact({ title, fact, value = fact.label, detail = fact.detail }: { title: string; fact: DailySummaryFact; value?: string; detail?: string }) {
  return <article className="daily-summary__fact">
    <span>{title}</span>
    <strong>{value}</strong>
    <p>{detail}</p>
    <small><b>Evidence:</b> {fact.evidence}</small>
  </article>;
}

export function OverviewPage() {
  const scope = useServerScope();
  const owner = useRole() === "owner";
  const [copied, setCopied] = useState(false);
  const [connectionHelpOpen, setConnectionHelpOpen] = useState(false);
  const [captureDuration, setCaptureDuration] = useState(30);
  const overview = useQuery({
    // A lifecycle request is accepted before Minecraft finishes transitioning.
    // Key the evidence view by the observed state so the daily summary cannot
    // remain on its pre-start or pre-stop snapshot while the hero has moved on.
    queryKey: ["overview", scope.profile.id, scope.state],
    queryFn: () => api<ProfileOverview>(`/profiles/${scope.profile.id}/overview`),
    refetchInterval: 10_000,
  });
  const data = overview.data;
  const refreshConnection = useMutation({
    mutationFn: () => api<unknown>(`/profiles/${scope.profile.id}/connection/refresh`, { method: "POST" }),
    onSuccess: () => void overview.refetch(),
  });
  const enableLan = useMutation({
    mutationFn: () => api<{ detail: string }>(`/profiles/${scope.profile.id}/connection/enable-lan`, { method: "POST" }),
    onSuccess: () => void overview.refetch(),
  });
  const diagnosticCaptures = useQuery({
    queryKey: ["diagnostic-captures", scope.profile.id],
    queryFn: () => api<DiagnosticCapture[]>(`/profiles/${scope.profile.id}/diagnostic-captures`),
    enabled: overview.data?.capabilities.tps === true,
  });
  const captureDiagnostic = useMutation({
    mutationFn: () => api<DiagnosticCapture>(`/profiles/${scope.profile.id}/diagnostic-captures`, {
      method: "POST",
      body: JSON.stringify({ duration_seconds: captureDuration }),
    }),
    onSuccess: () => void diagnosticCaptures.refetch(),
  });

  async function copyAddress() {
    if (!data?.join.address) return;
    await navigator.clipboard.writeText(data.join.address);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  if (!data) return <section className="card"><p className="empty-note">Building the server overview…</p>{overview.error && <p className="error">{overview.error.message}</p>}</section>;

  const current = data.metrics.current;
  const daily = data.daily_summary;

  return <>
    <section className="card daily-summary" aria-labelledby="daily-summary-heading">
      <div className="section-heading"><div><p className="eyebrow">At a glance</p><div className="heading-with-help"><h2 id="daily-summary-heading">Today on this server</h2><Tooltip label="How this summary chooses what to show">Each item names the recorded evidence behind it. The focus area shows only the most relevant warning or safe next task; detailed work stays in the linked workspace.</Tooltip></div></div><span>Live summary</span></div>
      <div className="daily-summary__facts">
        <DailyFact title="Playable state" fact={daily.playable} />
        <DailyFact title="Join address" fact={daily.join} value={daily.join.address ?? daily.join.label} detail={daily.join.address ? `${daily.join.label}. ${daily.join.detail}` : daily.join.detail} />
        <DailyFact title="Player capacity" fact={daily.players} />
        <DailyFact title="Last verified backup" fact={daily.backup} detail={daily.backup.created_at ? `${new Date(daily.backup.created_at).toLocaleString()}. ${daily.backup.detail}` : daily.backup.detail} />
        <DailyFact title="Next operation" fact={daily.next_operation} detail={daily.next_operation.at ? `${new Date(daily.next_operation.at).toLocaleString()}. ${daily.next_operation.detail}` : daily.next_operation.detail} />
      </div>
      <div className={`daily-summary__focus daily-summary__focus--${daily.focus.severity}`}>
        <div><span>{daily.focus.kind === "warning" ? "Most relevant warning" : "Recommended next step"}</span><strong>{daily.focus.title}</strong><p>{daily.focus.detail}</p><small><b>Evidence:</b> {daily.focus.evidence}</small></div>
        <Link className="button button--secondary button--small" to={daily.focus.to}>{daily.focus.kind === "warning" ? "Review warning" : "Open next step"}</Link>
      </div>
    </section>

    <section className="join-card card" aria-labelledby="join-heading">
      <div><p className="eyebrow">Minecraft connection</p><h2 id="join-heading">Join this server</h2><p>Use this local-network address from a device on the same network. Blockstead never presents a guessed router or internet address as confirmed.</p></div>
      {data.join.address
        ? <div className="join-address"><code>{data.join.host}</code><span>Port <strong>{data.join.port}</strong></span><Button className="button--secondary button--small" onClick={() => void copyAddress()}>{copied ? "Copied" : "Copy address"}</Button></div>
        : <div className="join-address join-address--unavailable"><strong>No local-network address detected</strong><span>Port <strong>{data.join.port}</strong></span></div>}
      <small>{data.join.address ? <>Local address: <code>{data.join.address}</code>.{data.join.candidate_hosts.length > 1 && ` Other detected local addresses: ${data.join.candidate_hosts.slice(1, 3).join(", ")}.`}</> : "Connect the Blockstead computer to a local network, then try the connection check again."}</small>
      <div className={`connection-status connection-status--${data.join.public.state}`} id="connection-help">
        {data.join.public.state === "unavailable"
          ? <div className="error" role="alert"><strong>Public address unavailable</strong><span>{data.join.public.detail}</span></div>
          : data.join.public.state === "local_only"
            ? <div className="warning"><strong>Internet access is blocked by this server’s bind address</strong><span>Blockstead detected a public IP, but this Minecraft server only listens on this computer.</span></div>
            : <div className="warning"><strong>Public IP detected: <code>{data.join.public.detected_ip}</code></strong><span>{data.join.public.detail} No public Minecraft address is being shown until the router and firewall mapping is confirmed.</span></div>}
        <Button className="button--secondary button--small" aria-expanded={connectionHelpOpen} onClick={() => setConnectionHelpOpen(open => !open)}>{connectionHelpOpen ? "Hide connection help" : "How to fix this"}</Button>
        {connectionHelpOpen && <aside className="connection-help-popover" aria-label="Public connection troubleshooting">
          <h3>Help friends join</h3>
          <p>Check that this computer is online without a VPN or proxy, that Minecraft is allowed through the host firewall, and that the router forwards the public port to this server’s local address and port <code>{data.join.public.server_port}</code>.</p>
          <p>Some internet providers use carrier-grade NAT or another router upstream, which prevents ordinary port forwarding. A router’s outside port can also differ from Minecraft’s local port, so Blockstead will not guess it.</p>
          <div className="connection-help-popover__actions">
            {owner && <Button className="button--secondary button--small" disabled={refreshConnection.isPending} onClick={() => refreshConnection.mutate()}>{refreshConnection.isPending ? "Checking…" : "Check public IP again"}</Button>}
            {owner && data.join.local_only && <Button className="button--small" disabled={enableLan.isPending} onClick={() => enableLan.mutate()}>{enableLan.isPending ? "Enabling…" : "Enable local-network access"}</Button>}
            <Link className="button button--quiet button--small" to="/help#connection-troubleshooting">Open full help guide</Link>
          </div>
          {refreshConnection.error && <p className="error" role="alert">{refreshConnection.error.message}</p>}
          {enableLan.data && <p className="success" role="status">{enableLan.data.detail}</p>}
          {enableLan.error && <p className="error" role="alert">{enableLan.error.message}</p>}
        </aside>}
      </div>
    </section>

    <section className="card" aria-labelledby="health-heading">
      <div className="section-heading"><div><p className="eyebrow">Recent trends</p><h2 id="health-heading">Server and host health</h2></div><span>{data.metrics.history.length} sample{data.metrics.history.length === 1 ? "" : "s"}</span></div>
      <div className="health-grid">
        <HistoryCard label="Host CPU" value={`${current.cpu_percent.toFixed(0)}%`} note="Computer running Blockstead" points={data.metrics.history} field="cpu_percent" percent />
        <HistoryCard label="Host memory" value={`${current.memory_percent.toFixed(0)}%`} note={`${formatBytes(current.memory_used_bytes)} of ${formatBytes(current.memory_total_bytes)}`} points={data.metrics.history} field="memory_percent" percent />
        <HistoryCard label="Data disk" value={`${current.disk_percent.toFixed(0)}%`} note={`${formatBytes(current.disk_used_bytes)} of ${formatBytes(current.disk_total_bytes)}`} points={data.metrics.history} field="disk_percent" percent />
        <HistoryCard label="World size" value={current.world_size_bytes != null ? formatBytes(current.world_size_bytes) : "—"} note="Recognized world folders" points={data.metrics.history} field="world_size_bytes" />
      </div>
      <small className="muted-note">Blockstead keeps up to seven days of once-per-minute host and world samples while a server is active. Tick evidence appears separately only when this profile exposes a supported source.</small>
    </section>

    <section className="card performance-panel" aria-labelledby="performance-heading">
      <div className="section-heading"><div><p className="eyebrow">Evidence, not guesswork</p><h2 id="performance-heading">Tick performance</h2></div><Link to={`/servers/${scope.profile.id}/world-care`}>Open World Care</Link></div>
      {data.performance.state === "unsupported"
        ? <p className="empty-note">{data.performance.detail}</p>
        : data.performance.tps || data.performance.mspt
          ? <>
            <div className="performance-grid">
              <article><span>TPS · 1 minute</span><strong>{data.performance.tps?.one_minute?.toFixed(2) ?? "—"}</strong><small>Target is 20.00</small></article>
              <article><span>TPS · 5 minutes</span><strong>{data.performance.tps?.five_minutes?.toFixed(2) ?? "—"}</strong><small>Longer trend</small></article>
              <article><span>MSPT · 5 seconds</span><strong>{data.performance.mspt?.five_seconds?.toFixed(2) ?? "—"}</strong><small>Lower is better; under 50 ms supports 20 TPS</small></article>
              <article><span>MSPT · 60 seconds</span><strong>{data.performance.mspt?.sixty_seconds?.toFixed(2) ?? "—"}</strong><small>Longer trend</small></article>
            </div>
            <small className="muted-note">Source: {data.performance.source}. Sampled every {data.performance.sampling_period_seconds} seconds; last response {sampledTime(data.performance.sampled_at)}. {data.performance.detail}</small>
          </>
          : <div className="warning performance-unavailable"><strong>Tick evidence is not available yet</strong><span>{data.performance.detail}</span></div>}
      {data.capabilities.tps && <div className="performance-capture">
        <div>
          <strong>Capture a bounded Spark profile</strong>
          <p>Runs only while this Paper server is live, stops automatically, and keeps the owner’s raw transcript local until you download it. No viewer link is requested or uploaded.</p>
        </div>
        <div className="performance-capture__actions">
          <label>Duration<select aria-label="Diagnostic capture duration" value={captureDuration} onChange={event => setCaptureDuration(Number(event.target.value))}><option value={30}>30 seconds</option><option value={60}>1 minute</option><option value={120}>2 minutes</option></select></label>
          {owner && <Button className="button--secondary button--small" disabled={!scope.running || captureDiagnostic.isPending} onClick={() => captureDiagnostic.mutate()}>{captureDiagnostic.isPending ? "Capturing…" : "Capture local profile"}</Button>}
        </div>
        {captureDiagnostic.error && <p className="error" role="alert">{captureDiagnostic.error.message}</p>}
        {captureDiagnostic.data && <p className="success" role="status">{captureDiagnostic.data.detail}</p>}
        {diagnosticCaptures.data?.length ? <ul className="performance-capture__history" aria-label="Local diagnostic captures">{diagnosticCaptures.data.slice(0, 3).map(capture => <li key={capture.id}><div><strong>{capture.status === "completed" ? "Local profile ready" : capture.status === "in_progress" ? "Capture in progress" : "Profile unavailable"}</strong><small>{new Date(capture.created_at).toLocaleString()} · {capture.duration_seconds} seconds · {capture.size_bytes == null ? "no transcript" : formatBytes(capture.size_bytes)}</small></div>{capture.download_url ? <a className="button button--quiet button--small" href={capture.download_url}>Download transcript</a> : <small>{capture.detail}</small>}</li>)}</ul> : null}
      </div>}
    </section>

    <div className="overview-columns">
      <section className="card overview-action-card" aria-labelledby="attention-heading">
        <div className="section-heading"><div><p className="eyebrow">Protection and readiness</p><h2 id="attention-heading">Needs attention</h2></div><span>{data.warnings.length || "Clear"}</span></div>
        {data.warnings.length ? <ul className="overview-list">{data.warnings.map(warning => <li key={warning.code} className={`overview-list__${warning.severity}`}><div><strong>{warning.title}</strong><p>{warning.detail}</p></div><Link to={warning.to}>Resolve</Link></li>)}</ul> : <p className="overview-clear">No readiness, crash, storage, or backup warnings right now.</p>}
      </section>

      <section className="card overview-activity" aria-labelledby="activity-heading">
        <div className="section-heading"><div><p className="eyebrow">Latest changes</p><h2 id="activity-heading">Recent activity</h2></div><span>{data.activity.length || "Quiet"}</span></div>
        {data.activity.length ? <ul className="overview-list">{data.activity.map(event => <li key={event.id}><div><strong>{event.category.replaceAll("_", " ")}</strong><p>{event.detail}</p><small>{new Date(event.created_at).toLocaleString()}</small></div><Link to={`/activity?profile_id=${encodeURIComponent(scope.profile.id)}&incident=${encodeURIComponent(event.id)}#incident-story`}>View story</Link></li>)}</ul> : <p className="overview-clear">No recent activity has been recorded for this server.</p>}
      </section>
    </div>

    {owner && <PrerequisitesPanel profileId={scope.profile.id} />}

    <details className="card diagnostics">
      <summary>Diagnostics</summary>
      <p>Technical details for troubleshooting. Normal server care should not require these values.</p>
      <dl><div><dt>Process ID</dt><dd>{scope.pid ?? "—"}</dd></div><div><dt>Last exit code</dt><dd>{scope.exitCode ?? "—"}</dd></div><div><dt>Configured bind</dt><dd>{data.join.bind_address ?? "All interfaces"}</dd></div><div><dt>Process memory</dt><dd>{current.process_memory_bytes != null ? formatBytes(current.process_memory_bytes) : "—"}</dd></div><div><dt>Minecraft version</dt><dd>{scope.profile.minecraft_version ?? "Not recorded"}</dd></div><div><dt>Server software</dt><dd>{serverSoftwareLabel(scope.profile)}</dd></div><div><dt>Server software version</dt><dd>{serverSoftwareVersion(scope.profile)}</dd></div></dl>
    </details>
  </>;
}
