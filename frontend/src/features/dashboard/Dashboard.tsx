import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, clearCsrf, type ImportScan, type LogEvent, type ProcessState, type Profile } from "../../api/client";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import { PlayersPanel } from "../players/PlayersPanel";
import { SettingsPanel } from "../settings/SettingsPanel";
import { SystemPanel } from "../system/SystemPanel";

const fixturePath = "fixtures/servers/vanilla-fixture";
const quickCommands = [
  { label: "Who is online?", command: "list" },
  { label: "Broadcast hello", command: "say Hello from Blockstead" },
  { label: "Show allowlist", command: "whitelist list" },
];

export function Dashboard({ onLogout }: { onLogout: () => void }) {
  const client = useQueryClient();
  const [command, setCommand] = useState("");
  const [path, setPath] = useState(fixturePath);
  const [scan, setScan] = useState<ImportScan | null>(null);
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [notice, setNotice] = useState("");
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state"), refetchInterval: 1000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  useEffect(() => { api<LogEvent[]>("/server/logs").then(setLogs).catch(() => undefined); }, []);
  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/api/v1/server/logs/ws`);
    socket.onmessage = event => {
      const payload: unknown = event.data;
      if (typeof payload === "string") setLogs(current => [...current.slice(-399), JSON.parse(payload) as LogEvent]);
    };
    return () => socket.close();
  }, []);
  const action = useMutation({ mutationFn: ({ endpoint, body }: { endpoint: string; body?: object }) => api<unknown>(endpoint, { method: "POST", body: body ? JSON.stringify(body) : undefined }), onSuccess: () => { void client.invalidateQueries(); }, onError: e => setNotice(e.message) });
  async function doScan(event: FormEvent) { event.preventDefault(); setNotice(""); try { setScan(await api<ImportScan>("/imports/scan", { method: "POST", body: JSON.stringify({ path }) })); } catch (e) { setNotice(e instanceof Error ? e.message : "Scan failed."); } }
  async function importProfile() { if (!scan) return; try { await api("/profiles", { method: "POST", body: JSON.stringify({ name: "Vanilla test fixture", path: scan.canonical_path }) }); setScan(null); await client.invalidateQueries({ queryKey: ["profiles"] }); } catch (e) { setNotice(e instanceof Error ? e.message : "Import failed."); } }
  function send(event: FormEvent) { event.preventDefault(); if (!command.trim()) return; action.mutate({ endpoint: "/server/command", body: { command } }); setCommand(""); }
  async function logout() { await api("/auth/logout", { method: "POST" }); clearCsrf(); onLogout(); }
  const current = state.data ?? { state: "UNKNOWN" as const, pid: null, exit_code: null, reason: "Checking server state" };
  const fixtureProfile = profiles.data?.find(profile => profile.is_fixture);
  const hasFixture = fixtureProfile != null;
  const running = current.state === "RUNNING";
  return <div className="app-shell"><header className="topbar"><a className="brand" href="#main"><span className="brand-mark" aria-hidden="true">B</span><span>Blockstead</span></a><div className="server-summary"><span className="summary-label">Test server</span><StatusBadge state={current.state} /></div><Button className="button--quiet" onClick={() => void logout()}>Sign out</Button></header><div className="layout"><nav aria-label="Main navigation"><a className="active" href="#overview">Overview</a><a href="#console">Console</a><a href="#players">Players</a><a href="#settings">Settings</a><a href="#system">System</a><span aria-disabled="true">Backups <small>Next</small></span></nav><main id="main"><section className="hero" id="overview"><div><p className="eyebrow">Family vanilla · Fixture</p><h1>Your server, at a glance</h1><p>{current.reason}</p></div><div className="hero-actions"><Button disabled={!hasFixture || !["STOPPED", "CRASHED", "DEGRADED"].includes(current.state)} onClick={() => action.mutate({ endpoint: "/server/start", body: { mode: "normal" } })}>Start fixture</Button><Button className="button--secondary" disabled={!['RUNNING', 'STARTING', 'DEGRADED'].includes(current.state)} onClick={() => action.mutate({ endpoint: "/server/stop" })}>Stop safely</Button><Button className="button--secondary" disabled={!running} onClick={() => action.mutate({ endpoint: "/server/restart", body: { mode: "normal" } })}>Restart</Button>{current.state === "STOPPING" && <Button className="button--danger" onClick={() => action.mutate({ endpoint: "/server/force-stop" })}>Force stop</Button>}</div></section>{notice && <div className="error" role="alert">{notice}</div>}<section className="metrics" aria-label="Server summary"><article><span>State</span><strong>{current.state}</strong></article><article><span>Process ID</span><strong>{current.pid ?? "—"}</strong></article><article><span>Exit code</span><strong>{current.exit_code ?? "—"}</strong></article><article><span>Profiles</span><strong>{profiles.data?.length ?? 0}</strong></article></section>{!hasFixture && <section className="card"><p className="eyebrow">First safe workflow</p><h2>Import the sanitized fixture</h2><p>The scan is read-only. Blockstead will show the plan before it records anything.</p><form className="inline-form" onSubmit={event => { void doScan(event); }}><label>Server folder<input value={path} onChange={e => setPath(e.target.value)} /></label><Button>Scan folder</Button></form>{scan && <div className="scan-plan"><h3>Import plan</h3><p>Detected: {scan.distribution} {scan.minecraft_version}</p><ul>{scan.plan.map(item => <li key={item}>{item}</li>)}</ul><Button onClick={() => void importProfile()}>Confirm profile record</Button></div>}</section>}<section className="card console" id="console"><div className="section-heading"><div><p className="eyebrow">Owned fixture process</p><h2>Live server log</h2></div><span>{logs.length} lines</span></div><div className="log" role="log" aria-live="polite">{logs.length ? logs.map(entry => <div key={entry.sequence}><time>{new Date(entry.timestamp).toLocaleTimeString()}</time><span>{entry.line}</span></div>) : <p className="empty">Start the fixture to see logs here.</p>}</div><div className="quick-commands" aria-label="Guided commands">{quickCommands.map(item => <Button key={item.command} className="button--secondary button--small" disabled={!running} onClick={() => action.mutate({ endpoint: "/server/command", body: { command: item.command } })}>{item.label}</Button>)}</div><form className="command" onSubmit={send}><label htmlFor="command">Minecraft console command</label><div><input id="command" value={command} onChange={e => setCommand(e.target.value)} disabled={current.state !== "RUNNING"} placeholder="say Hello from Blockstead" /><Button disabled={current.state !== "RUNNING"}>Send command</Button></div><small>This sends text only to the managed Minecraft fixture—not to an operating-system shell.</small></form></section>{fixtureProfile && <PlayersPanel profileId={fixtureProfile.id} running={running} />}{fixtureProfile && <SettingsPanel profileId={fixtureProfile.id} />}<SystemPanel /></main></div></div>;
}
