import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, clearCsrf, type ImportScan, type LogEvent, type ProcessState, type Profile } from "../../api/client";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import { PlayersPanel } from "../players/PlayersPanel";
import { SettingsPanel } from "../settings/SettingsPanel";
import { SystemPanel } from "../system/SystemPanel";
import { ExtensionsPanel } from "../extensions/ExtensionsPanel";
import { ModpacksPanel } from "../extensions/ModpacksPanel";
import { PrerequisitesPanel } from "../extensions/PrerequisitesPanel";

const fixturePath = "fixtures/servers/vanilla-fixture";
const quickCommands = [
  { label: "Who is online?", command: "list" },
  { label: "Broadcast hello", command: "say Hello from Blockstead" },
  { label: "Show allowlist", command: "whitelist list" },
];

const navItems = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "console", label: "Console", icon: "terminal" },
  { id: "players", label: "Players", icon: "users" },
  { id: "extensions", label: "Extensions", icon: "blocks" },
  { id: "modpacks", label: "Modpacks", icon: "package" },
  { id: "settings", label: "Settings", icon: "sliders" },
  { id: "system", label: "System", icon: "pulse" },
] as const;

function NavIcon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    terminal: <><path d="m5 7 4 4-4 4" /><path d="M12 17h7" /></>,
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>,
    blocks: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="8.5" y="14" width="7" height="7" rx="1" /></>,
    package: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" /><path d="m4.5 7.5 7.5 4 7.5-4" /><path d="M12 21v-9.5" /></>,
    sliders: <><path d="M4 21v-7" /><path d="M4 10V3" /><path d="M12 21v-9" /><path d="M12 8V3" /><path d="M20 21v-5" /><path d="M20 12V3" /><path d="M1 14h6" /><path d="M9 8h6" /><path d="M17 16h6" /></>,
    pulse: <><path d="M3 12h4l2.5-7 5 14 2.5-7h4" /></>,
  };
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

export function Dashboard({ onLogout }: { onLogout: () => void }) {
  const client = useQueryClient();
  const [command, setCommand] = useState("");
  const [path, setPath] = useState(fixturePath);
  const [scan, setScan] = useState<ImportScan | null>(null);
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [notice, setNotice] = useState("");
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [activeSection, setActiveSection] = useState("overview");
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
  useEffect(() => {
    const sections = navItems.map(item => document.getElementById(item.id)).filter((section): section is HTMLElement => Boolean(section));
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible?.target.id) setActiveSection(visible.target.id);
    }, { rootMargin: "-18% 0px -65% 0px", threshold: [0, .1, .4] });
    sections.forEach(section => observer.observe(section));
    return () => observer.disconnect();
  }, [profiles.data?.length]);

  const action = useMutation({
    mutationFn: ({ endpoint, body }: { endpoint: string; body?: object }) => api<unknown>(endpoint, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: () => { setNotice(""); void client.invalidateQueries(); },
    onError: e => setNotice(e.message),
  });

  async function doScan(event: FormEvent) {
    event.preventDefault(); setNotice("");
    try { setScan(await api<ImportScan>("/imports/scan", { method: "POST", body: JSON.stringify({ path }) })); }
    catch (e) { setNotice(e instanceof Error ? e.message : "Scan failed."); }
  }
  async function importProfile() {
    if (!scan) return;
    try {
      await api("/profiles", { method: "POST", body: JSON.stringify({ name: "Vanilla test fixture", path: scan.canonical_path }) });
      setScan(null);
      await client.invalidateQueries({ queryKey: ["profiles"] });
    } catch (e) { setNotice(e instanceof Error ? e.message : "Import failed."); }
  }
  function send(event: FormEvent) {
    event.preventDefault();
    if (!command.trim()) return;
    action.mutate({ endpoint: "/server/command", body: { command } });
    setCommand("");
  }
  async function logout() { await api("/auth/logout", { method: "POST" }); clearCsrf(); onLogout(); }

  const current = state.data ?? { state: "UNKNOWN" as const, pid: null, exit_code: null, reason: "Checking server state" };
  const selectedProfile = profiles.data?.find(profile => profile.id === selectedProfileId) ?? profiles.data?.find(profile => profile.id === current.profile_id) ?? profiles.data?.[0];
  const selectedId = selectedProfile?.id ?? "";
  const running = current.state === "RUNNING";
  const stopped = ["STOPPED", "CRASHED"].includes(current.state);

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="#main" aria-label="Blockstead home"><span className="brand-mark" aria-hidden="true"><span>B</span></span><span className="brand-copy">Blockstead<small>Minecraft server care</small></span></a>
      <div className="server-summary"><span className="summary-label">{selectedProfile?.name ?? "No server selected"}</span><StatusBadge state={current.state} /></div>
      <Button className="button--quiet sign-out" onClick={() => void logout()}>Sign out</Button>
    </header>
    <div className="layout">
      <aside className="sidebar">
        <nav aria-label="Main navigation">
          <p className="nav-heading">Workspace</p>
          {navItems.map(item => <a key={item.id} className={activeSection === item.id ? "active" : ""} href={`#${item.id}`} aria-current={activeSection === item.id ? "location" : undefined} onClick={() => setActiveSection(item.id)}><NavIcon name={item.icon} /><span>{item.label}</span></a>)}
          <span className="nav-disabled" aria-disabled="true"><NavIcon name="package" /><span>Backups</span><small>Next</small></span>
        </nav>
        <div className="privacy-card"><span className="privacy-card__icon" aria-hidden="true">◆</span><div><strong>Local by design</strong><small>Your server data stays on this machine.</small></div></div>
      </aside>
      <main id="main">
        <section className={`hero hero--${current.state.toLowerCase()}`} id="overview">
          <div className="hero-copy"><p className="eyebrow">{selectedProfile?.name ?? "Server control"}</p><h1>Your server, at a glance</h1><p>{current.reason}</p><div className="hero-status"><span className="hero-state"><i aria-hidden="true" />Server {current.state.toLowerCase()}</span>{current.pid && <span>PID {current.pid}</span>}</div></div>
          <div className="hero-actions">
            <label>Active profile<select value={selectedId} onChange={event => setSelectedProfileId(event.target.value)} disabled={current.state !== "STOPPED"}>{profiles.data?.map(profile => <option key={profile.id} value={profile.id}>{profile.name} · {profile.distribution}</option>)}</select></label>
            <div className="control-actions"><Button disabled={!selectedId || !["STOPPED", "CRASHED", "DEGRADED"].includes(current.state)} onClick={() => action.mutate({ endpoint: "/server/start", body: { profile_id: selectedId, mode: "normal" } })}>Start server</Button><Button className="button--secondary" disabled={!['RUNNING', 'STARTING', 'DEGRADED'].includes(current.state)} onClick={() => action.mutate({ endpoint: "/server/stop" })}>Stop safely</Button><Button className="button--secondary" disabled={!running || !current.profile_id} onClick={() => action.mutate({ endpoint: "/server/restart", body: { profile_id: current.profile_id, mode: "normal" } })}>Restart</Button>{current.state === "STOPPING" && <Button className="button--danger" onClick={() => action.mutate({ endpoint: "/server/force-stop" })}>Force stop</Button>}</div>
          </div>
        </section>
        {notice && <div className="error page-notice" role="alert">{notice}</div>}
        <section className="metrics" aria-label="Server summary">
          <article><span>Server state</span><strong>{current.state}</strong><small>{running ? "Accepting commands" : "Not using host resources"}</small></article>
          <article><span>Process ID</span><strong>{current.pid ?? "—"}</strong><small>{current.pid ? "Managed by Blockstead" : "No active process"}</small></article>
          <article><span>Last exit</span><strong>{current.exit_code ?? "—"}</strong><small>{current.exit_code == null ? "No exit recorded" : current.exit_code === 0 ? "Clean shutdown" : "Needs attention"}</small></article>
          <article><span>Profiles</span><strong>{profiles.data?.length ?? 0}</strong><small>Ready to manage</small></article>
        </section>
        {!profiles.data?.length && <section className="card onboarding-card"><p className="eyebrow">First safe workflow</p><h2>Import a server folder</h2><p>The scan is read-only. Blockstead records a profile without changing server files.</p><form className="inline-form" onSubmit={event => { void doScan(event); }}><label>Server folder<input value={path} onChange={e => setPath(e.target.value)} /></label><Button>Scan folder</Button></form>{scan && <div className="scan-plan"><h3>Import plan</h3><p>Detected: {scan.distribution} {scan.minecraft_version}</p><ul>{scan.plan.map(item => <li key={item}>{item}</li>)}</ul><Button onClick={() => void importProfile()}>Confirm profile record</Button></div>}</section>}
        {selectedProfile && <PrerequisitesPanel profileId={selectedProfile.id} />}
        <section className="card console" id="console">
          <div className="section-heading"><div><p className="eyebrow">Managed server process</p><h2>Live server log</h2></div><span className="live-count"><i />{logs.length} lines</span></div>
          <div className="log" role="log" aria-live="polite">{logs.length ? logs.map(entry => <div key={entry.sequence}><time>{new Date(entry.timestamp).toLocaleTimeString()}</time><span>{entry.line}</span></div>) : <p className="empty">Start a server to see logs here.</p>}</div>
          <div className="quick-commands" aria-label="Guided commands">{quickCommands.map(item => <Button key={item.command} className="button--secondary button--small" disabled={!running} onClick={() => action.mutate({ endpoint: "/server/command", body: { command: item.command } })}>{item.label}</Button>)}</div>
          <form className="command" onSubmit={send}><label htmlFor="command">Minecraft console command</label><div><input id="command" value={command} onChange={e => setCommand(e.target.value)} disabled={current.state !== "RUNNING"} placeholder="give PlayerName minecraft:diamond 64" /><Button disabled={current.state !== "RUNNING"}>Send command</Button></div><small>Any one-line vanilla Minecraft server command is sent to the selected server—not to an operating-system shell.</small></form>
        </section>
        {selectedProfile && <PlayersPanel profileId={selectedProfile.id} running={running} />}
        {selectedProfile && <ExtensionsPanel profileId={selectedProfile.id} stopped={stopped} />}
        <ModpacksPanel stopped={stopped} onCreated={setSelectedProfileId} />
        {selectedProfile && <SettingsPanel profileId={selectedProfile.id} />}
        <SystemPanel />
        <footer className="app-footer"><span className="brand-mark brand-mark--small" aria-hidden="true"><span>B</span></span><p><strong>Blockstead</strong><br />Quiet, local care for your Minecraft world.</p></footer>
      </main>
    </div>
  </div>;
}
