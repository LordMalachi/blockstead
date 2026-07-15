import { useQuery } from "@tanstack/react-query";
import { api, type SystemMetrics } from "../../api/client";
import { formatBytes, formatUptime } from "../../lib/format";

export function SystemPanel() {
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<SystemMetrics>("/system/metrics"), refetchInterval: 2000 });
  const data = metrics.data;
  return <section className="card" id="system"><div className="section-heading"><div><p className="eyebrow">This computer</p><h2>System health</h2></div><span>{data ? "Live" : "Waiting"}</span></div>{!data ? <p className="empty-note">Collecting the first sample…</p> : <div className="metrics metrics--panel" aria-label="Host metrics"><article><span>Host CPU</span><strong>{data.cpu_percent.toFixed(0)}%</strong></article><article><span>Host memory</span><strong>{data.memory.percent.toFixed(0)}%</strong><small>{formatBytes(data.memory.used_bytes)} of {formatBytes(data.memory.total_bytes)}</small></article><article><span>Data disk</span><strong>{data.disk.percent.toFixed(0)}%</strong><small>{formatBytes(data.disk.used_bytes)} of {formatBytes(data.disk.total_bytes)}</small></article><article><span>Server uptime</span><strong>{data.process.uptime_seconds != null ? formatUptime(data.process.uptime_seconds) : "—"}</strong>{data.process.memory_bytes != null && <small>{formatBytes(data.process.memory_bytes)} in use</small>}</article></div>}<small className="muted-note">Measurements come from the machine running Blockstead. The uptime tile tracks the managed server process only.</small></section>;
}
