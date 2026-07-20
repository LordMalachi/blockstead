import { useQuery } from "@tanstack/react-query";
import { api, type DiagnosticsReport } from "../../api/client";

const SHOWN_PROBLEMS = 6;

export function DiagnosticsPanel() {
  const report = useQuery({ queryKey: ["diagnostics"], queryFn: () => api<DiagnosticsReport>("/system/diagnostics"), refetchInterval: 15000 });
  const data = report.data;
  const problems = data ? [...data.recent_errors].reverse() : [];
  const java = data?.java_runtimes[0];
  return <section className="card diagnostics" id="diagnostics" aria-labelledby="diagnostics-heading">
    <div className="section-heading">
      <div><p className="eyebrow">Support</p><h2 id="diagnostics-heading">Diagnostics</h2></div>
      <a className="button button--secondary button--small" href="/api/v1/system/diagnostics/report" download>Download report</a>
    </div>
    {!data ? <p className="empty-note">Collecting installation details…</p> : <>
      <dl>
        <div><dt>Blockstead</dt><dd>{data.application.version}</dd></div>
        <div><dt>Dashboard address</dt><dd>{data.settings.bind_host}:{data.settings.port}</dd></div>
        <div><dt>Java</dt><dd>{java ? `${java.major} (${data.java_runtimes.length} found)` : "None found"}</dd></div>
        <div><dt>Servers</dt><dd>{data.profiles.length}</dd></div>
        <div><dt>Data disk</dt><dd>{data.host.disk.percent.toFixed(0)}% full</dd></div>
      </dl>
      <h3 className="diagnostic-log-heading">Recent problems</h3>
      {problems.length === 0 ? <p className="empty-note">No warnings or errors have been recorded recently.</p>
        : <ul className="diagnostic-log" aria-label="Recent warnings and errors">{problems.slice(0, SHOWN_PROBLEMS).map(entry => <li key={`${entry.at}-${entry.message}`} className={entry.level === "WARNING" ? "" : "diagnostic-log--error"}><strong>{entry.level.toLowerCase()} · {new Date(entry.at).toLocaleString()}</strong><p>{entry.message}</p></li>)}</ul>}
      {problems.length > SHOWN_PROBLEMS && <p className="muted-note">Showing the {SHOWN_PROBLEMS} most recent of {problems.length} recorded problems. The downloaded report contains all of them.</p>}
    </>}
    <small className="muted-note">The report includes software settings, host health, profile names, recent actions, and application logs. Account names inside home-folder paths are masked, but server and player names may remain. Review it before sharing; Blockstead never uploads it.</small>
  </section>;
}
