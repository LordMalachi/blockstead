import { useState } from "react";
import { Navigate, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ProcessState, type Profile } from "../../api/client";
import { Button } from "../../components/Button";
import { useRole } from "../shell/role";
import { scopeFor } from "./scope";
import { serverSoftwareIdentity } from "./server-version";

export function ServerLayout() {
  const { profileId = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const section = useLocation().pathname.split("/")[3] ?? "overview";
  const [notice, setNotice] = useState("");
  const role = useRole();
  const owner = role === "owner";
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state"), refetchInterval: 1000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const action = useMutation({
    mutationFn: ({ endpoint, body }: { endpoint: string; body?: object }) => api<unknown>(endpoint, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: () => { setNotice(""); void client.invalidateQueries(); },
    onError: error => setNotice(error.message),
  });

  const profile = profiles.data?.find(entry => entry.id === profileId);
  if (!profiles.data) return <section className="card"><p className="empty-note">Opening this server…</p></section>;
  if (!profile) return <Navigate to="/servers" replace />;

  const snapshot = state.data ?? { state: "UNKNOWN" as const, pid: null, exit_code: null, reason: "Checking server state" };
  const scope = scopeFor(profile, snapshot, profiles.data);

  return <>
    <section className={`hero hero--${scope.state.toLowerCase()}`}>
      <div className="hero-copy">
        <p className="eyebrow">{serverSoftwareIdentity(profile)} · Minecraft {profile.minecraft_version ?? "version not recorded"}</p>
        <h1>{profile.name}</h1>
        <p>{scope.reason}</p>
        <div className="hero-status"><span className="hero-state"><i aria-hidden="true" />Server {scope.state.toLowerCase()}</span>{scope.pid != null && <span>PID {scope.pid}</span>}</div>
      </div>
      <div className="hero-actions">
        <label>Active server<select value={profile.id} onChange={event => { void navigate(`/servers/${event.target.value}/${section}`); }}>{profiles.data.map(entry => <option key={entry.id} value={entry.id}>{entry.name} · {entry.distribution}</option>)}</select></label>
        {owner ? <div className="control-actions" aria-busy={action.isPending}>
          <Button disabled={action.isPending || !scope.canStart} onClick={() => action.mutate({ endpoint: "/server/start", body: { profile_id: profile.id, mode: "normal" } })}>Start server</Button>
          <Button className="button--secondary" disabled={action.isPending || !scope.isActive || !["RUNNING", "STARTING", "DEGRADED"].includes(scope.state)} onClick={() => action.mutate({ endpoint: "/server/stop" })}>Stop safely</Button>
          <Button className="button--secondary" disabled={action.isPending || !scope.isActive || !scope.running} onClick={() => action.mutate({ endpoint: "/server/restart", body: { profile_id: profile.id, mode: "normal" } })}>Restart</Button>
          {scope.isActive && scope.state === "STOPPING" && <Button className="button--danger" disabled={action.isPending} onClick={() => action.mutate({ endpoint: "/server/force-stop" })}>{action.isPending ? "Force stopping…" : "Force stop"}</Button>}
        </div> : <p className="muted-note">View-only account: server controls and raw files are hidden.</p>}
      </div>
    </section>
    {notice && <div className="error page-notice" role="alert">{notice}</div>}
    <Outlet context={scope} />
  </>;
}
