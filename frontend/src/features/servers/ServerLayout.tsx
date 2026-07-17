import { useState } from "react";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ProcessState, type Profile } from "../../api/client";
import { Button } from "../../components/Button";
import { scopeFor } from "./scope";

export function ServerLayout() {
  const { profileId = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const section = useLocation().pathname.split("/")[3] ?? "overview";
  const [notice, setNotice] = useState("");
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state"), refetchInterval: 1000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const action = useMutation({
    mutationFn: ({ endpoint, body }: { endpoint: string; body?: object }) => api<unknown>(endpoint, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: () => { setNotice(""); void client.invalidateQueries(); },
    onError: error => setNotice(error.message),
  });

  const profile = profiles.data?.find(entry => entry.id === profileId);
  if (!profiles.data) return <section className="card"><p className="empty-note">Opening this server…</p></section>;
  if (!profile) return <section className="card"><p className="eyebrow">Server workspace</p><h2>That server is not here</h2><p>This link points at a profile Blockstead does not know about. It may have been removed.</p><Link className="button" to="/servers">Back to your servers</Link></section>;

  const snapshot = state.data ?? { state: "UNKNOWN" as const, pid: null, exit_code: null, reason: "Checking server state" };
  const scope = scopeFor(profile, snapshot, profiles.data);

  return <>
    <section className={`hero hero--${scope.state.toLowerCase()}`}>
      <div className="hero-copy">
        <p className="eyebrow">{profile.distribution} · {profile.minecraft_version ?? "version unknown"}</p>
        <h1>{profile.name}</h1>
        <p>{scope.reason}</p>
        <div className="hero-status"><span className="hero-state"><i aria-hidden="true" />Server {scope.state.toLowerCase()}</span>{scope.pid != null && <span>PID {scope.pid}</span>}</div>
      </div>
      <div className="hero-actions">
        <label>Active server<select value={profile.id} onChange={event => { void navigate(`/servers/${event.target.value}/${section}`); }}>{profiles.data.map(entry => <option key={entry.id} value={entry.id}>{entry.name} · {entry.distribution}</option>)}</select></label>
        <div className="control-actions">
          <Button disabled={!scope.canStart} onClick={() => action.mutate({ endpoint: "/server/start", body: { profile_id: profile.id, mode: "normal" } })}>Start server</Button>
          <Button className="button--secondary" disabled={!scope.isActive || !["RUNNING", "STARTING", "DEGRADED"].includes(scope.state)} onClick={() => action.mutate({ endpoint: "/server/stop" })}>Stop safely</Button>
          <Button className="button--secondary" disabled={!scope.isActive || !scope.running} onClick={() => action.mutate({ endpoint: "/server/restart", body: { profile_id: profile.id, mode: "normal" } })}>Restart</Button>
          {scope.isActive && scope.state === "STOPPING" && <Button className="button--danger" onClick={() => action.mutate({ endpoint: "/server/force-stop" })}>Force stop</Button>}
        </div>
      </div>
    </section>
    {notice && <div className="error page-notice" role="alert">{notice}</div>}
    <Outlet context={scope} />
  </>;
}
