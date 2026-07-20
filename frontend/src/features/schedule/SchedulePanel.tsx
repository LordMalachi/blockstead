import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AutomationCapabilities, type AutomationEvent, type AutomationRun, type Schedule } from "../../api/client";
import { Button } from "../../components/Button";
import { Tooltip } from "../../components/Tooltip";

const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const blank = {
  enabled: true,
  start_time: "",
  stop_time: "",
  backup_before_stop: true,
  power_off_after_stop: false,
  wake_time: "",
  weekdays: [0, 1, 2, 3, 4, 5, 6],
  only_when_empty: false,
};

type FormState = typeof blank;

function localDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function duration(value: number) {
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`;
}

function minimumLocalTime() {
  const value = new Date(Date.now() + 60_000);
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 16);
}

function maintenanceSteps(form: FormState) {
  const steps = ["Announce maintenance", "Flush Minecraft saves"];
  if (form.backup_before_stop) steps.push("Create a verified backup");
  steps.push("Stop the server safely");
  if (form.power_off_after_stop) steps.push("Shut down the Linux host");
  return steps;
}

export function SchedulePanel({ profileId }: { profileId: string }) {
  const cache = useQueryClient();
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: () => api<Schedule[]>("/schedules") });
  const capabilities = useQuery({ queryKey: ["automation-capabilities"], queryFn: () => api<AutomationCapabilities>("/automation/capabilities") });
  const [form, setForm] = useState<FormState>(blank);
  const [oneTime, setOneTime] = useState("");
  const [notice, setNotice] = useState("");
  const existing = schedules.data?.find(item => item.profile_id === profileId);
  const powerCapable = capabilities.data?.host_power ?? existing?.power_capable ?? false;
  const steps = useMemo(() => maintenanceSteps(form), [form]);
  const scheduleBody = () => JSON.stringify({
    profile_id: profileId,
    ...form,
    start_time: form.start_time || null,
    stop_time: form.stop_time || null,
    wake_time: form.wake_time || null,
  });

  useEffect(() => {
    setForm(existing ? {
      enabled: existing.enabled,
      start_time: existing.start_time ?? "",
      stop_time: existing.stop_time ?? "",
      backup_before_stop: existing.backup_before_stop,
      power_off_after_stop: existing.power_off_after_stop,
      wake_time: existing.wake_time ?? "",
      weekdays: existing.weekdays,
      only_when_empty: existing.only_when_empty,
    } : blank);
  }, [profileId, existing]);

  const refresh = async () => { await cache.invalidateQueries({ queryKey: ["schedules"] }); };
  const save = useMutation({
    mutationFn: () => api<Schedule>(`/schedules/${profileId}`, {
      method: "PUT",
      body: scheduleBody(),
    }),
    onSuccess: async () => { setNotice("Automation plan saved."); await refresh(); },
  });
  const createEvent = useMutation({
    mutationFn: () => api<AutomationEvent>(`/profiles/${profileId}/automation-events`, {
      method: "POST",
      body: JSON.stringify({
        run_at: oneTime,
        backup_before_stop: form.backup_before_stop,
        power_off_after_stop: form.power_off_after_stop,
        wake_time: form.wake_time || null,
        only_when_empty: form.only_when_empty,
      }),
    }),
    onSuccess: async () => { setOneTime(""); setNotice("One-time maintenance added."); await refresh(); },
  });
  const cancelEvent = useMutation({
    mutationFn: (eventId: string) => api<void>(`/profiles/${profileId}/automation-events/${eventId}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const run = useMutation({
    mutationFn: async (confirmPower: boolean) => {
      await api<Schedule>(`/schedules/${profileId}`, { method: "PUT", body: scheduleBody() });
      return api<AutomationRun>(`/schedules/${profileId}/run`, { method: "POST", body: JSON.stringify({ action: "maintenance", confirm_power: confirmPower }) });
    },
    onSuccess: async result => { setNotice(result.detail); await refresh(); },
  });

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm(current => ({ ...current, [key]: value }));
  const toggleDay = (day: number) => set("weekdays", form.weekdays.includes(day) ? form.weekdays.filter(item => item !== day) : [...form.weekdays, day].sort());
  const preset = (weekdays: number[], start = form.start_time, stop = form.stop_time) => setForm(current => ({ ...current, enabled: true, weekdays, start_time: start || "09:00", stop_time: stop || "23:00" }));
  const runNow = () => {
    const confirmed = !form.power_off_after_stop || window.confirm("This plan will shut down the Linux computer after stopping the server. Run it now?");
    if (confirmed) run.mutate(form.power_off_after_stop);
  };
  const error = save.error ?? createEvent.error ?? cancelEvent.error ?? run.error;

  return <div className="automation-page" id="schedule">
    <section className="card automation-hero">
      <div className="section-heading"><div><p className="eyebrow">Automation</p><h2>Server schedule</h2></div><span>{existing?.enabled ? "Active" : "Not scheduled"}</span></div>
      <p>Choose the days Blockstead should start and care for this server. Times use this computer’s local time, and every maintenance run follows the visible sequence below.</p>
      <div className="preset-row" aria-label="Schedule presets">
        <Button className="button--quiet" onClick={() => preset([0, 1, 2, 3, 4])}>Weekdays</Button>
        <Button className="button--quiet" onClick={() => preset([0, 1, 2, 3, 4, 5, 6], "", "23:00")}>Every night</Button>
        <Button className="button--quiet" onClick={() => preset([5, 6])}>Weekend only</Button>
      </div>
      <div className="weekday-picker" aria-label="Run on weekdays">{days.map((label, index) => <label key={label} className={form.weekdays.includes(index) ? "selected" : ""}><input type="checkbox" checked={form.weekdays.includes(index)} onChange={() => toggleDay(index)} />{label}</label>)}</div>
      <div className="schedule-grid">
        <label className="check-label"><input type="checkbox" checked={form.enabled} onChange={event => set("enabled", event.target.checked)} /> Enable recurring plan</label>
        <label>Start server<input type="time" value={form.start_time} onChange={event => set("start_time", event.target.value)} /></label>
        <label>Maintenance stop<input type="time" value={form.stop_time} onChange={event => set("stop_time", event.target.value)} /></label>
        <label className="check-label"><input type="checkbox" checked={form.backup_before_stop} onChange={event => set("backup_before_stop", event.target.checked)} /> Back up before stopping</label>
        <label className="check-label"><input type="checkbox" checked={form.only_when_empty} onChange={event => set("only_when_empty", event.target.checked)} /> Stop only when nobody is online</label>
      </div>
      <div className="power-schedule">
        <div className="heading-with-help"><h3>Computer power <span className="capability-tag">Linux only</span></h3><Tooltip label="How scheduled power works">Blockstead stops Minecraft safely before asking the installed Linux helper to shut down. Waking later requires compatible RTC hardware; no network wake or router automation is performed.</Tooltip></div>
        <label className="check-label"><input type="checkbox" checked={form.power_off_after_stop} onChange={event => set("power_off_after_stop", event.target.checked)} disabled={!powerCapable || !form.stop_time} /> Shut down the computer after the safe stop</label>
        {!powerCapable && <small>Unavailable until the Linux installer power helper is present. Blockstead never offers an unverified host-power action.</small>}
        {form.power_off_after_stop && <label>Wake computer at<input type="time" value={form.wake_time} onChange={event => set("wake_time", event.target.value)} /><small>Requires compatible RTC wake hardware.</small></label>}
      </div>
      {form.weekdays.length === 0 && <p className="error">Choose at least one day.</p>}
      {error && <p className="error" role="alert">{error.message}</p>}
      {notice && <p className="success" role="status">{notice}</p>}
      <div className="automation-actions"><Button onClick={() => save.mutate()} disabled={save.isPending || form.weekdays.length === 0}>{save.isPending ? "Saving…" : "Save plan"}</Button><Button className="button--secondary" onClick={runNow} disabled={form.weekdays.length === 0 || run.isPending}>{run.isPending ? "Running…" : "Run maintenance now"}</Button></div>
    </section>

    <section className="card automation-sequence">
      <p className="eyebrow">Execution preview</p><h2>What Blockstead will do</h2>
      <ol>{steps.map((step, index) => <li key={step}><span>{index + 1}</span><strong>{step}</strong></li>)}</ol>
      {form.only_when_empty && <p className="muted-note">Before step 1, Blockstead checks the local Minecraft status. If player status is unavailable or anyone is online, it leaves the server running and records why.</p>}
    </section>

    <section className="card">
      <div className="section-heading"><div><p className="eyebrow">Coming up</p><h2>Next three executions</h2></div></div>
      {existing?.next_executions.length ? <ol className="execution-list">{existing.next_executions.map(item => <li key={`${item.kind}-${item.at}`}><div><strong>{item.label}</strong><span>{localDate(item.at)}</span></div><small>{item.steps.join(" → ")}</small></li>)}</ol> : <p className="empty-state">Save an enabled plan or add one-time maintenance to see upcoming work.</p>}
    </section>

    <section className="card">
      <p className="eyebrow">One-time work</p><h2>Maintenance events</h2>
      <p>Queue a maintenance run without changing the recurring days. It uses the sequence currently previewed above.</p>
      <div className="one-time-form"><label>Local date and time<input type="datetime-local" value={oneTime} min={minimumLocalTime()} onChange={event => setOneTime(event.target.value)} /></label><Button onClick={() => createEvent.mutate()} disabled={!oneTime || createEvent.isPending || form.power_off_after_stop && !powerCapable}>Add event</Button></div>
      {existing?.one_time_events.length ? <ul className="event-list">{existing.one_time_events.map(event => <li key={event.id}><div><strong>{localDate(event.run_at)}</strong><small>{maintenanceSteps({ ...form, backup_before_stop: event.backup_before_stop, power_off_after_stop: event.power_off_after_stop }).join(" → ")}</small></div><Button className="button--quiet" onClick={() => cancelEvent.mutate(event.id)}>Cancel</Button></li>)}</ul> : <p className="empty-state">No one-time maintenance is queued.</p>}
    </section>

    <section className="card">
      <p className="eyebrow">Execution history</p><h2>Recent automation</h2>
      {existing?.history.length ? <ul className="history-list">{existing.history.map(item => <li key={item.id}><span className={`run-status run-status--${item.status}`}>{item.status}</span><div><strong>{item.action === "start" ? "Start server" : "Maintenance"} · {item.trigger.replace("_", " ")}</strong><p>{item.detail}</p><small>{localDate(item.started_at)} · {duration(item.duration_ms)}</small></div></li>)}</ul> : <p className="empty-state">Runs will appear here with their result, duration, and any failure reason.</p>}
    </section>
  </div>;
}
