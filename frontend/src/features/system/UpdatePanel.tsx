import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type UpdateStatus } from "../../api/client";
import { Button } from "../../components/Button";

const SUMMARY: Record<UpdateStatus["decision"], string> = {
  current: "Up to date",
  install: "Installing now",
  stop_server_first: "Installing once the server stops",
  waiting_for_players: "Waiting for players to leave",
  manual: "Update available",
};

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Not yet";
}

export function UpdatePanel() {
  const client = useQueryClient();
  const status = useQuery({
    queryKey: ["updates"],
    queryFn: () => api<UpdateStatus>("/updates/status"),
  });
  const check = useMutation({
    mutationFn: () => api<UpdateStatus>("/updates/check", { method: "POST" }),
    onSuccess: data => client.setQueryData(["updates"], data),
  });
  const data = status.data;

  return <section className="card" id="updates" aria-labelledby="updates-heading">
    <div className="section-heading">
      <div><p className="eyebrow">Software</p><h2 id="updates-heading">Blockstead updates</h2></div>
      <Button className="button--secondary button--small" onClick={() => check.mutate()} disabled={check.isPending || status.data?.installing}>
        {check.isPending ? "Checking…" : "Check now"}
      </Button>
    </div>
    {!data ? <p className="empty-note">Checking which version is installed…</p> : <>
      <dl>
        <div><dt>Status</dt><dd>{SUMMARY[data.decision]}</dd></div>
        <div><dt>Installed</dt><dd>{data.build.label}</dd></div>
        <div><dt>Newest available</dt><dd>{data.latest ? data.latest.short_commit : "Not checked yet"}</dd></div>
        <div><dt>Last checked</dt><dd>{when(data.checked_at)}</dd></div>
        <div><dt>Automatic updates</dt><dd>{data.supported ? (data.automatic ? "On" : "Off") : "Not available here"}</dd></div>
      </dl>
      {check.isError && <p className="error" role="alert">{check.error.message}</p>}
      {data.error && !check.isError && <p className="warning" role="status">{data.error}</p>}
      {data.last_result && <p className={data.last_result.state === "failed" ? "error" : "success"} role="status">
        {data.last_result.detail}
      </p>}
    </>}
    <small className="muted-note">
      {data?.supported
        ? "Blockstead checks GitHub for a newer version when it starts and every few hours after that, then installs it while nobody is playing. Your worlds, settings, administrator accounts, and backups are always kept, and the previous version is restored automatically if an update does not start cleanly."
        : "This copy of Blockstead was not set up by the Linux installer, so it cannot update itself. Checking still works, and tells you whether a newer version exists."}
    </small>
  </section>;
}
