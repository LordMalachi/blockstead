import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type UpdateStatus } from "../../api/client";
import { Button } from "../../components/Button";

const SUMMARY: Record<UpdateStatus["decision"], string> = {
  current: "Up to date",
  install: "Installing now",
  stop_server_first: "Installing once the server stops",
  waiting_for_players: "Waiting for players to leave",
  manual: "Update available",
  failed: "Update needs attention",
};

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Not yet";
}

function resultTone(state: NonNullable<UpdateStatus["last_result"]>["state"]): string {
  if (state === "failed") return "error";
  if (state === "succeeded") return "success";
  return "warning";
}

function failedCurrentBuild(status: UpdateStatus): boolean {
  return status.last_result?.state === "failed"
    && (!status.latest || status.last_result.commit === status.latest.commit);
}

function decisionSummary(status: UpdateStatus): string {
  if ((status.decision === "failed" || failedCurrentBuild(status)) && status.last_result?.retryable) {
    return "Retry scheduled";
  }
  if (status.decision === "failed" || failedCurrentBuild(status)) return "Update needs attention";
  return SUMMARY[status.decision];
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
  const retry = useMutation({
    mutationFn: () => api<UpdateStatus>("/updates/install", { method: "POST" }),
    onSuccess: data => client.setQueryData(["updates"], data),
  });
  const data = status.data;
  const busy = check.isPending || retry.isPending || Boolean(data?.installing);
  const canRetry = Boolean(data?.supported && data.latest
    && (data.decision === "failed" || failedCurrentBuild(data)));

  return <section className="card" id="updates" aria-labelledby="updates-heading">
    <div className="section-heading">
      <div><p className="eyebrow">Software</p><h2 id="updates-heading">Blockstead updates</h2></div>
      <div className="update-actions">
        <Button className="button--secondary button--small" onClick={() => check.mutate()} disabled={busy}>
          {check.isPending ? "Checking…" : "Check now"}
        </Button>
        {canRetry && <Button className="button--small" onClick={() => retry.mutate()} disabled={busy}>
          {retry.isPending ? "Retrying…" : "Retry update"}
        </Button>}
      </div>
    </div>
    {!data ? <p className="empty-note">Checking which version is installed…</p> : <>
      <dl>
        <div><dt>Status</dt><dd>{decisionSummary(data)}</dd></div>
        <div><dt>Installed</dt><dd>{data.build.label}</dd></div>
        <div><dt>Newest available</dt><dd>{data.latest ? data.latest.short_commit : "Not checked yet"}</dd></div>
        <div><dt>Last checked</dt><dd>{when(data.checked_at)}</dd></div>
        <div><dt>Automatic updates</dt><dd>{data.supported ? (data.automatic ? "On" : "Off") : "Not available here"}</dd></div>
      </dl>
      {check.isError && <p className="error" role="alert">{check.error.message}</p>}
      {retry.isError && <p className="error" role="alert">{retry.error.message}</p>}
      {data.error && !check.isError && <p className="warning" role="status">{data.error}</p>}
      {data.last_result && <p className={resultTone(data.last_result.state)} role="status">
        {data.last_result.detail}
      </p>}
    </>}
    <small className="muted-note">
      {data?.supported
        ? "Blockstead follows the newest tested build from the project's main branch. It installs while nobody is playing, restores a server that was running beforehand, and rolls back without repeatedly retrying a failed build. Your worlds, settings, administrator accounts, and backups are always kept."
        : "This copy of Blockstead was not set up by the Linux installer, so it cannot update itself. Checking still works, and tells you whether a newer version exists."}
    </small>
  </section>;
}
