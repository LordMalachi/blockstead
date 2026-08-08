import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, type ActivityFeed, type ActivityIncident, type LocalNotifications, type NotificationPreferences, type Profile } from "../../api/client";
import { Button } from "../../components/Button";
import { Tooltip } from "../../components/Tooltip";

const groups = ["lifecycle", "backup", "maintenance", "settings", "extension", "player", "files", "automation", "update", "system"];

function incidentHref(eventId: string, current: URLSearchParams): string {
  const next = new URLSearchParams(current);
  next.set("incident", eventId);
  return `/activity?${next.toString()}#incident-story`;
}

function IncidentStory({ incident, close }: { incident: ActivityIncident; close: () => void }) {
  return <section className="card incident-story" id="incident-story" aria-labelledby="incident-story-heading">
    <div className="section-heading">
      <div><p className="eyebrow">Incident story</p><div className="heading-with-help"><h2 id="incident-story-heading">{incident.anchor.title}</h2><Tooltip label="How Blockstead builds this story">Recorded facts come from saved events. Observed timing only says when events happened near one another. A possible explanation is explicitly unconfirmed and is never presented as the cause.</Tooltip></div></div>
      <Button className="button--quiet button--small" onClick={close}>Close story</Button>
    </div>
    <p className={`incident-story__symptom incident-story__symptom--${incident.anchor.severity}`}><strong>{incident.anchor.severity === "success" ? "Selected event" : "Recorded symptom"}</strong><span>{incident.anchor.detail}</span><time dateTime={incident.anchor.created_at}>{new Date(incident.anchor.created_at).toLocaleString()}</time></p>
    <div className="incident-story__interpretation">
      <article><span>Observed timing</span><strong>{incident.observed_timing.label}</strong><p>{incident.observed_timing.detail}</p></article>
      <article className={`incident-story__explanation incident-story__explanation--${incident.possible_explanation.state}`}><span>Possible explanation — not confirmed</span><p>{incident.possible_explanation.detail}</p></article>
    </div>
    <section className="incident-story__facts" aria-labelledby="recorded-facts-heading">
      <div className="heading-with-help"><h3 id="recorded-facts-heading">Recorded facts</h3><Tooltip label="What counts as a recorded fact">These are persisted lifecycle, backup, settings, extension, schedule, or diagnostic events for this server. Their order shows timing, not proof that one caused another.</Tooltip></div>
      {incident.recorded_facts.length ? <ol>{incident.recorded_facts.map(fact => <li key={fact.id}>
        <span className={`activity-event__marker activity-event__marker--${fact.severity}`} aria-hidden="true" />
        <div><div className="incident-story__fact-heading"><strong>{fact.title}</strong><time dateTime={fact.created_at}>{new Date(fact.created_at).toLocaleString()}</time></div><p>{fact.detail}</p><small>{fact.group} · {fact.result}</small><Link to={fact.recovery_to}>Open related workspace</Link></div>
      </li>)}</ol> : <p className="empty-note">No other recorded events were close enough to include.</p>}
    </section>
    <section className="incident-story__logs" aria-labelledby="log-context-heading">
      <div className="heading-with-help"><h3 id="log-context-heading">Raw log context</h3><Tooltip label="What is safe to share">Log context and the downloadable evidence report are kept local and are never uploaded automatically. They can still include server and player names, so review them before sharing.</Tooltip></div>
      <p>{incident.log_context.detail}</p>
      {incident.log_context.entries.length ? <div className="incident-log" role="log" aria-label="Log entries near this incident">{incident.log_context.entries.map((entry, index) => <div key={`${entry.at}-${entry.logger}-${index}`}><time dateTime={entry.at}>{new Date(entry.at).toLocaleTimeString()}</time><span><b>{entry.level}</b> · {entry.logger}</span><code>{entry.message}</code></div>)}</div> : <p className="empty-note">No raw log entries were recorded near this event.</p>}
      <a className="button button--quiet button--small" href={incident.anchor.report_url} download>Download raw evidence report</a>
    </section>
    <aside className="incident-story__action" aria-label="Safe next action"><div><span>Safe next action</span><strong>{incident.safe_next_action.label}</strong><p>{incident.safe_next_action.detail}</p></div><Link className="button button--secondary" to={incident.safe_next_action.to}>Open next step</Link></aside>
  </section>;
}

export function ActivityPage() {
  const queryClient = useQueryClient();
  const [urlSearch, setUrlSearch] = useSearchParams();
  const profileId = urlSearch.get("profile_id") ?? "";
  const category = urlSearch.get("category") ?? "";
  const result = urlSearch.get("result") ?? "";
  const incidentId = urlSearch.get("incident") ?? "";
  const [preferenceState, setPreferenceState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const search = new URLSearchParams();
  if (profileId) search.set("profile_id", profileId);
  if (category) search.set("category", category);
  if (result) search.set("result", result);
  const feed = useQuery({
    queryKey: ["activity", profileId, category, result],
    queryFn: () => api<ActivityFeed>(`/activity${search.size ? `?${search}` : ""}`),
  });
  const incident = useQuery({
    queryKey: ["activity-incident", incidentId],
    queryFn: () => api<ActivityIncident>(`/activity/${encodeURIComponent(incidentId)}/incident`),
    enabled: !!incidentId,
  });
  useEffect(() => {
    if (incident.data && window.location.hash === "#incident-story") {
      document.getElementById("incident-story")?.scrollIntoView?.({ block: "start" });
    }
  }, [incident.data]);
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: () => api<LocalNotifications>("/notifications") });
  const preferences = useQuery({ queryKey: ["notification-preferences"], queryFn: () => api<NotificationPreferences>("/notification-preferences") });
  const acknowledge = useMutation({
    mutationFn: () => api<void>("/notifications/acknowledge", { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  function updateFilter(name: "profile_id" | "category" | "result", value: string) {
    const next = new URLSearchParams(urlSearch);
    if (value) next.set(name, value);
    else next.delete(name);
    next.delete("incident");
    setUrlSearch(next, { replace: true });
  }

  function closeIncident() {
    const next = new URLSearchParams(urlSearch);
    next.delete("incident");
    setUrlSearch(next, { replace: true });
  }

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setPreferenceState("saving");
    try {
      await api<NotificationPreferences>("/notification-preferences", {
        method: "PUT",
        body: JSON.stringify({
          server_crashes: data.has("server_crashes"),
          failed_backups: data.has("failed_backups"),
          failed_automations: data.has("failed_automations"),
          low_disk_space: data.has("low_disk_space"),
          completed_updates: data.has("completed_updates"),
          show_player_avatars: data.has("show_player_avatars"),
        }),
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["notification-preferences"] }),
        queryClient.invalidateQueries({ queryKey: ["notifications"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
      ]);
      setPreferenceState("saved");
    } catch {
      setPreferenceState("error");
    }
  }

  return <>
    <section className="page-head"><div><p className="eyebrow">What changed</p><h1>Activity</h1><p>Follow server operations across every profile. Open an incident story to compare recorded facts, nearby timing, redacted logs, and one safe next step without treating timing as proof of cause.</p></div></section>

    {!!notifications.data?.alerts.length && <section className="card activity-alerts" aria-labelledby="alerts-heading">
      <div className="section-heading"><div><p className="eyebrow">Needs attention</p><h2 id="alerts-heading">Local notifications</h2></div><div className="activity-alert-actions"><Tooltip label="What does Mark seen do?">It clears unread event alerts. An ongoing condition such as low disk space remains visible until it is fixed.</Tooltip><Button className="button--secondary button--small" onClick={() => acknowledge.mutate()} disabled={acknowledge.isPending}>Mark seen</Button></div></div>
      <div className="activity-alert-list">{notifications.data.alerts.map(alert => <article className={`activity-alert activity-alert--${alert.severity}`} key={alert.id}><div><strong>{alert.title}</strong><p>{alert.detail}</p></div><Link to={alert.recovery_to}>Open recovery</Link></article>)}</div>
    </section>}

    {incidentId && (incident.isPending
      ? <section className="card incident-story" id="incident-story"><p className="empty-note">Connecting the recorded evidence…</p></section>
      : incident.isError
        ? <section className="card incident-story" id="incident-story"><p className="error" role="alert">This incident story could not be loaded.</p><Button className="button--secondary button--small" onClick={() => void incident.refetch()}>Try again</Button><Button className="button--quiet button--small" onClick={closeIncident}>Close story</Button></section>
        : incident.data && <IncidentStory incident={incident.data} close={closeIncident} />)}

    <div className="activity-layout">
      <section className="card activity-feed" aria-labelledby="history-heading">
        <div className="section-heading"><div><p className="eyebrow">Timeline</p><div className="heading-with-help"><h2 id="history-heading">History</h2><Tooltip label="How do outcomes and support reports work?">Accepted means Blockstead handed off the request; success means a tracked operation finished. An event report includes redacted system context and application logs from roughly fifteen minutes around that event. Review it before sharing.</Tooltip></div></div><span>{feed.data?.total ?? 0} events</span></div>
        <div className="activity-filters">
          <label>Server<select value={profileId} onChange={event => updateFilter("profile_id", event.target.value)}><option value="">All servers</option>{profiles.data?.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
          <label>Category<select value={category} onChange={event => updateFilter("category", event.target.value)}><option value="">All categories</option>{groups.map(group => <option value={group} key={group}>{group}</option>)}</select></label>
          <label>Outcome<select value={result} onChange={event => updateFilter("result", event.target.value)}><option value="">All outcomes</option><option value="success">Success</option><option value="accepted">Accepted</option><option value="failed">Failed</option><option value="skipped">Skipped</option></select></label>
        </div>
        {feed.isPending ? <p className="muted-note">Loading activity…</p> : feed.isError ? <p className="error">Activity could not be loaded.</p> : feed.data?.events.length ? <ol className="activity-timeline">{feed.data.events.map(item => <li key={item.id} className={`activity-event activity-event--${item.severity}`}>
          <span className="activity-event__marker" aria-hidden="true" />
          <div className="activity-event__body"><div className="activity-event__heading"><div><strong>{item.title}</strong><span className={`result result--${item.severity}`}>{item.result}</span></div><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></div><p>{item.detail}</p><small>{item.actor}{item.profile ? ` · ${item.profile.name}` : " · Workspace"} · {item.group}</small><div className="row-actions"><Link className="button button--secondary button--small" to={incidentHref(item.id, urlSearch)}>View incident story</Link><Link className="button button--quiet button--small" to={item.recovery_to}>{item.severity === "danger" ? "Open recovery" : "Related workspace"}</Link><a className="button button--quiet button--small" href={item.report_url} download>Download support report</a></div></div>
        </li>)}</ol> : <p className="activity-empty">No activity matches these filters.</p>}
      </section>

      <aside className="card activity-preferences"><p className="eyebrow">Local alerts</p><h2>Notification preferences</h2><p>Choose which important changes appear here. Blockstead does not send these alerts or reports anywhere on its own.</p>
        {preferences.data && <form onSubmit={event => void savePreferences(event)} key={JSON.stringify(preferences.data)}>
          <label className="vanilla-switch"><span><strong>Server crashes</strong><small>Surface an unexpected Minecraft exit.</small></span><input name="server_crashes" type="checkbox" defaultChecked={preferences.data.server_crashes} /></label>
          <label className="vanilla-switch"><span><strong>Failed backups</strong><small>Keep failed world protection visible.</small></span><input name="failed_backups" type="checkbox" defaultChecked={preferences.data.failed_backups} /></label>
          <label className="vanilla-switch"><span><strong>Failed automation</strong><small>Surface scheduled starts, maintenance, or host-power steps that need attention.</small></span><input name="failed_automations" type="checkbox" defaultChecked={preferences.data.failed_automations} /></label>
          <label className="vanilla-switch"><span><strong>Low disk space</strong><small>Warn when the data disk reaches 90%.</small></span><input name="low_disk_space" type="checkbox" defaultChecked={preferences.data.low_disk_space} /></label>
          <label className="vanilla-switch"><span><strong>Completed updates</strong><small>Confirm a Blockstead update finished.</small></span><input name="completed_updates" type="checkbox" defaultChecked={preferences.data.completed_updates} /></label>
          <label className="vanilla-switch"><span><strong>Player avatars</strong><small>Show skin images on the Players page. The browser fetches them from crafatar.com by player ID — the only outbound request Blockstead makes on your behalf.</small></span><input name="show_player_avatars" type="checkbox" defaultChecked={preferences.data.show_player_avatars} /></label>
          <Button type="submit" disabled={preferenceState === "saving"}>{preferenceState === "saving" ? "Saving…" : "Save preferences"}</Button>
          {preferenceState === "saved" && <p className="success">Preferences saved.</p>}
          {preferenceState === "error" && <p className="error">Preferences could not be saved. Try again.</p>}
        </form>}
      </aside>
    </div>
  </>;
}
