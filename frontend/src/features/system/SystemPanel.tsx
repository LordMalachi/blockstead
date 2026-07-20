import { useQuery } from "@tanstack/react-query";
import { api, type SystemMetrics } from "../../api/client";
import { formatBytes, formatUptime } from "../../lib/format";
import { Tooltip } from "../../components/Tooltip";

export function SystemPanel() {
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<SystemMetrics>("/system/metrics"), refetchInterval: 2000 });
  const data = metrics.data;
  return <section className="card" id="system"><div className="section-heading"><div><p className="eyebrow">This computer</p><div className="heading-with-help"><h2>System health</h2><Tooltip label="What these measurements include">CPU and memory cover the whole computer. Data disk covers the storage volume holding Blockstead’s data. Uptime and process memory cover only this Minecraft server.</Tooltip></div></div><span>{data ? "Live" : "Waiting"}</span></div>{!data ? <p className="empty-note">Collecting the first sample…</p> : <div className="metrics metrics--panel" aria-label="Host metrics"><article><span>Host CPU</span><strong>{data.cpu_percent.toFixed(0)}%</strong></article><article><span>Host memory</span><strong>{data.memory.percent.toFixed(0)}%</strong><small>{formatBytes(data.memory.used_bytes)} of {formatBytes(data.memory.total_bytes)}</small></article><article><span>Data disk</span><strong>{data.disk.percent.toFixed(0)}%</strong><small>{formatBytes(data.disk.used_bytes)} of {formatBytes(data.disk.total_bytes)}</small></article><article><span>Server uptime</span><strong>{data.process.uptime_seconds != null ? formatUptime(data.process.uptime_seconds) : "—"}</strong>{data.process.memory_bytes != null && <small>{formatBytes(data.process.memory_bytes)} in use</small>}</article></div>}<small className="muted-note">CPU and memory describe the Blockstead computer. Data disk describes the storage volume holding Blockstead’s private data; server uptime tracks only Minecraft.</small></section>;
}
