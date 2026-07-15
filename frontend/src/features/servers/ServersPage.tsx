import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ImportScan, type PlayersView, type ProcessState, type Profile, type Schedule } from "../../api/client";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import { ModpacksPanel } from "../extensions/ModpacksPanel";
import { scopeFor, type ServerScope } from "./scope";

const fixturePath = "fixtures/servers/vanilla-fixture";

function nextScheduled(schedule: Schedule | undefined): string {
  if (!schedule?.enabled) return "No schedule";
  const now = new Date();
  const minutesNow = now.getHours() * 60 + now.getMinutes();
  const upcoming = [{ label: "Start", time: schedule.start_time }, { label: "Stop", time: schedule.stop_time }]
    .filter((entry): entry is { label: string; time: string } => Boolean(entry.time))
    .map(entry => { const [hours, minutes] = entry.time.split(":").map(Number); return { ...entry, wait: (hours * 60 + minutes - minutesNow + 1440) % 1440 }; })
    .sort((a, b) => a.wait - b.wait)[0];
  return upcoming ? `${upcoming.label} ${upcoming.time}` : "No schedule";
}

function ServerCard({ scope, allowlist, schedule, onAction }: { scope: ServerScope; allowlist: number | null; schedule: Schedule | undefined; onAction: (endpoint: string, body?: object) => void }) {
  const { profile } = scope;
  return <article className="server-card">
    <div className="server-card__head">
      <div><h3><Link to={`/servers/${profile.id}/overview`}>{profile.name}</Link></h3><p>{profile.distribution} · {profile.minecraft_version ?? "version unknown"}</p></div>
      <StatusBadge state={scope.state} />
    </div>
    <dl className="server-card__facts">
      <div><dt>Allowlist</dt><dd>{allowlist ?? "—"}</dd></div>
      <div><dt>Next schedule</dt><dd>{nextScheduled(schedule)}</dd></div>
      <div><dt>Last backup</dt><dd>No history yet</dd></div>
    </dl>
    <div className="server-card__actions">
      {scope.isActive && ["RUNNING", "STARTING", "DEGRADED"].includes(scope.state)
        ? <Button className="button--secondary" onClick={() => onAction("/server/stop")}>Stop safely</Button>
        : <Button disabled={!scope.canStart} onClick={() => onAction("/server/start", { profile_id: profile.id, mode: "normal" })}>Start server</Button>}
      <Link className="button button--quiet" to={`/servers/${profile.id}/overview`}>Open workspace</Link>
    </div>
    {scope.occupant && <small className="muted-note">{scope.reason}</small>}
  </article>;
}

export function ServersPage() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [path, setPath] = useState(fixturePath);
  const [scan, setScan] = useState<ImportScan | null>(null);
  const [notice, setNotice] = useState("");
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state"), refetchInterval: 1000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: () => api<Schedule[]>("/schedules") });
  const rosters = useQueries({
    queries: (profiles.data ?? []).map(profile => ({ queryKey: ["players", profile.id], queryFn: () => api<PlayersView>(`/profiles/${profile.id}/players`) })),
  });
  const action = useMutation({
    mutationFn: ({ endpoint, body }: { endpoint: string; body?: object }) => api<unknown>(endpoint, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: () => { setNotice(""); void client.invalidateQueries(); },
    onError: error => setNotice(error.message),
  });

  async function doScan(event: FormEvent) {
    event.preventDefault(); setNotice("");
    try { setScan(await api<ImportScan>("/imports/scan", { method: "POST", body: JSON.stringify({ path }) })); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Scan failed."); }
  }
  async function importProfile() {
    if (!scan) return;
    try {
      const created = await api<{ id: string }>("/profiles", { method: "POST", body: JSON.stringify({ name: "Vanilla test fixture", path: scan.canonical_path }) });
      setScan(null);
      await client.invalidateQueries({ queryKey: ["profiles"] });
      void navigate(`/servers/${created.id}/overview`);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Import failed."); }
  }

  const list = profiles.data ?? [];
  const snapshot = state.data ?? { state: "UNKNOWN" as const, pid: null, exit_code: null, reason: "Checking server state" };
  const hostFree = ["STOPPED", "CRASHED"].includes(snapshot.state);

  return <>
    <section className="page-head">
      <div><p className="eyebrow">Your servers</p><h1>Servers</h1><p>Every Minecraft world Blockstead looks after on this computer. Open one to reach its console, players, schedule, and settings.</p></div>
    </section>
    {notice && <div className="error page-notice" role="alert">{notice}</div>}
    {list.length > 0 && <div className="server-grid">{list.map((profile, index) => <ServerCard key={profile.id} scope={scopeFor(profile, snapshot, list)} allowlist={rosters[index]?.data?.allowlist.readable ? rosters[index].data.allowlist.players.length : null} schedule={schedules.data?.find(entry => entry.profile_id === profile.id)} onAction={(endpoint, body) => action.mutate({ endpoint, body })} />)}</div>}
    <section className={`card${list.length ? "" : " onboarding-card"}`}>
      <p className="eyebrow">{list.length ? "Add a server" : "First safe workflow"}</p>
      <h2>Import a server folder</h2>
      <p>The scan is read-only. Blockstead records a profile without changing server files.</p>
      <form className="inline-form" onSubmit={event => { void doScan(event); }}><label>Server folder<input value={path} onChange={event => setPath(event.target.value)} /></label><Button>Scan folder</Button></form>
      {scan && <div className="scan-plan"><h3>Import plan</h3><p>Detected: {scan.distribution} {scan.minecraft_version}</p><ul>{scan.plan.map(item => <li key={item}>{item}</li>)}</ul><Button onClick={() => void importProfile()}>Confirm profile record</Button></div>}
    </section>
    <ModpacksPanel stopped={hostFree} onCreated={id => { void navigate(`/servers/${id}/overview`); }} />
  </>;
}
