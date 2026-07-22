import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type ActivityFeed, type LocalNotifications, type NotificationPreferences, type Profile } from "../../api/client";
import { Button } from "../../components/Button";
import { Tooltip } from "../../components/Tooltip";

const groups = ["lifecycle", "backup", "settings", "extension", "player", "automation", "update", "system"];

export function ActivityPage() {
  const queryClient = useQueryClient();
  const [profileId, setProfileId] = useState("");
  const [category, setCategory] = useState("");
  const [result, setResult] = useState("");
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
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: () => api<LocalNotifications>("/notifications") });
  const preferences = useQuery({ queryKey: ["notification-preferences"], queryFn: () => api<NotificationPreferences>("/notification-preferences") });
  const acknowledge = useMutation({
    mutationFn: () => api<void>("/notifications/acknowledge", { method: "POST" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

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
          low_disk_space: data.has("low_disk_space"),
          completed_updates: data.has("completed_updates"),
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
    <section className="page-head"><div><p className="eyebrow">What changed</p><h1>Activity</h1><p>Follow server operations across every profile. A support report downloaded from an event centers the logs and system context on that moment.</p></div></section>

    {!!notifications.data?.alerts.length && <section className="card activity-alerts" aria-labelledby="alerts-heading">
      <div className="section-heading"><div><p className="eyebrow">Needs attention</p><h2 id="alerts-heading">Local notifications</h2></div><div className="activity-alert-actions"><Tooltip label="What does Mark seen do?">It clears unread event alerts. An ongoing condition such as low disk space remains visible until it is fixed.</Tooltip><Button className="button--secondary button--small" onClick={() => acknowledge.mutate()} disabled={acknowledge.isPending}>Mark seen</Button></div></div>
      <div className="activity-alert-list">{notifications.data.alerts.map(alert => <article className={`activity-alert activity-alert--${alert.severity}`} key={alert.id}><div><strong>{alert.title}</strong><p>{alert.detail}</p></div><Link to={alert.recovery_to}>Open recovery</Link></article>)}</div>
    </section>}

    <div className="activity-layout">
      <section className="card activity-feed" aria-labelledby="history-heading">
        <div className="section-heading"><div><p className="eyebrow">Timeline</p><div className="heading-with-help"><h2 id="history-heading">History</h2><Tooltip label="How do outcomes and support reports work?">Accepted means Blockstead handed off the request; success means a tracked operation finished. An event report includes redacted system context and application logs from roughly fifteen minutes around that event. Review it before sharing.</Tooltip></div></div><span>{feed.data?.total ?? 0} events</span></div>
        <div className="activity-filters">
          <label>Server<select value={profileId} onChange={event => setProfileId(event.target.value)}><option value="">All servers</option>{profiles.data?.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
          <label>Category<select value={category} onChange={event => setCategory(event.target.value)}><option value="">All categories</option>{groups.map(group => <option value={group} key={group}>{group}</option>)}</select></label>
          <label>Outcome<select value={result} onChange={event => setResult(event.target.value)}><option value="">All outcomes</option><option value="success">Success</option><option value="accepted">Accepted</option><option value="failed">Failed</option><option value="skipped">Skipped</option></select></label>
        </div>
        {feed.isPending ? <p className="muted-note">Loading activity…</p> : feed.isError ? <p className="error">Activity could not be loaded.</p> : feed.data?.events.length ? <ol className="activity-timeline">{feed.data.events.map(item => <li key={item.id} className={`activity-event activity-event--${item.severity}`}>
          <span className="activity-event__marker" aria-hidden="true" />
          <div className="activity-event__body"><div className="activity-event__heading"><div><strong>{item.title}</strong><span className={`result result--${item.severity}`}>{item.result}</span></div><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></div><p>{item.detail}</p><small>{item.actor}{item.profile ? ` · ${item.profile.name}` : " · Workspace"} · {item.group}</small><div className="row-actions"><Link className="button button--secondary button--small" to={item.recovery_to}>{item.severity === "danger" ? "Open recovery" : "View details"}</Link><a className="button button--quiet button--small" href={item.report_url} download>Download support report</a></div></div>
        </li>)}</ol> : <p className="activity-empty">No activity matches these filters.</p>}
      </section>

      <aside className="card activity-preferences"><p className="eyebrow">Local alerts</p><h2>Notification preferences</h2><p>Choose which important changes appear here. Blockstead does not send these alerts or reports anywhere on its own.</p>
        {preferences.data && <form onSubmit={event => void savePreferences(event)} key={JSON.stringify(preferences.data)}>
          <label className="vanilla-switch"><span><strong>Server crashes</strong><small>Surface an unexpected Minecraft exit.</small></span><input name="server_crashes" type="checkbox" defaultChecked={preferences.data.server_crashes} /></label>
          <label className="vanilla-switch"><span><strong>Failed backups</strong><small>Keep failed world protection visible.</small></span><input name="failed_backups" type="checkbox" defaultChecked={preferences.data.failed_backups} /></label>
          <label className="vanilla-switch"><span><strong>Low disk space</strong><small>Warn when the data disk reaches 90%.</small></span><input name="low_disk_space" type="checkbox" defaultChecked={preferences.data.low_disk_space} /></label>
          <label className="vanilla-switch"><span><strong>Completed updates</strong><small>Confirm a Blockstead update finished.</small></span><input name="completed_updates" type="checkbox" defaultChecked={preferences.data.completed_updates} /></label>
          <Button type="submit" disabled={preferenceState === "saving"}>{preferenceState === "saving" ? "Saving…" : "Save preferences"}</Button>
          {preferenceState === "saved" && <p className="success">Preferences saved.</p>}
          {preferenceState === "error" && <p className="error">Preferences could not be saved. Try again.</p>}
        </form>}
      </aside>
    </div>
  </>;
}
