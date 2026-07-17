import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RawSettingsApplyResult, type RawSettingsPreview, type RawSettingsView, type SettingChange, type SettingEntry, type SettingsApplyResult, type SettingsPreview, type SettingsView } from "../../api/client";
import { Button } from "../../components/Button";

type DraftValue = string | boolean;
const categories = ["Gameplay", "Players", "World", "Network", "Performance"] as const;

function draftFor(view: SettingsView): Record<string, DraftValue> {
  return Object.fromEntries(view.settings.map(entry => [entry.key, entry.type === "boolean" ? entry.value === true : entry.value == null ? "" : String(entry.value)]));
}

function shown(value: string | number | boolean | null): string {
  if (value === null || value === "") return "Not set";
  if (typeof value === "boolean") return value ? "On" : "Off";
  return String(value);
}

function inputFor(entry: SettingEntry, value: DraftValue, set: (value: DraftValue) => void) {
  if (entry.type === "boolean") return <label className="setting-toggle"><input type="checkbox" aria-label={entry.label} checked={value === true} onChange={event => set(event.target.checked)} /><span>{value === true ? "On" : "Off"}</span></label>;
  if (entry.options.length) return <select aria-label={entry.label} value={String(value)} onChange={event => set(event.target.value)}>{entry.options.map(option => <option key={option} value={option}>{option[0].toUpperCase() + option.slice(1)}</option>)}</select>;
  return <input aria-label={entry.label} type={entry.type === "integer" ? "number" : "text"} min={entry.minimum ?? undefined} max={entry.maximum ?? undefined} value={String(value)} onChange={event => set(event.target.value)} />;
}

function RawEditor({ profileId, onSaved }: { profileId: string; onSaved: (result: RawSettingsApplyResult) => void }) {
  const cache = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const raw = useQuery({
    queryKey: ["settings-raw", profileId],
    queryFn: () => api<RawSettingsView>(`/profiles/${profileId}/settings/raw`),
    enabled: open,
  });
  useEffect(() => { setOpen(false); setText(null); }, [profileId]);
  const view = raw.data;
  const content = text ?? view?.content ?? "";
  const check = useMutation({
    mutationFn: (payload: { revision: string; content: string }) => api<RawSettingsPreview>(`/profiles/${profileId}/settings/raw/preview`, { method: "POST", body: JSON.stringify(payload) }),
  });
  const save = useMutation({
    mutationFn: (payload: { revision: string; content: string }) => api<RawSettingsApplyResult>(`/profiles/${profileId}/settings/raw`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: result => {
      setOpen(false);
      setText(null);
      check.reset();
      void cache.invalidateQueries({ queryKey: ["settings-raw", profileId] });
      onSaved(result);
    },
    onError: () => void cache.invalidateQueries({ queryKey: ["settings-raw", profileId] }),
  });
  const checked = check.data && check.variables?.content === content ? check.data : null;

  function close() { setOpen(false); setText(null); check.reset(); save.reset(); }

  return <section className="raw-editor" aria-label="Advanced raw editor">
    <div className="section-heading"><div><p className="eyebrow">Advanced</p><h3>Raw file editor</h3></div><span>Recovery protected</span></div>
    {!open && <>
      <p className="muted-note">Edit the complete server.properties file. Every save is validated first and creates a private recovery snapshot; hidden secret values never reach the browser.</p>
      <div className="settings-actions"><Button className="button--secondary" onClick={() => setOpen(true)}>Open raw editor</Button></div>
    </>}
    {open && (raw.isLoading
      ? <p className="empty-note">Loading server.properties…</p>
      : !view?.editable
        ? <><p className="empty-note">{view?.problem ?? "This file cannot be edited right now."}</p><div className="settings-actions"><Button className="button--quiet" onClick={close}>Close</Button></div></>
        : <>
          {view.secret_keys.length > 0 && <p className="muted-note">Hidden values ({view.secret_keys.join(", ")}) appear as •••••••• and stay unchanged unless you type a new value over them.</p>}
          <textarea className="raw-editor__text" aria-label="server.properties content" rows={14} spellCheck={false} value={content} onChange={event => { setText(event.target.value); save.reset(); }} />
          <div className="settings-actions">
            <Button className="button--secondary" disabled={check.isPending} onClick={() => { if (view.revision) check.mutate({ revision: view.revision, content }); }}>{check.isPending ? "Checking…" : "Check changes"}</Button>
            <Button disabled={!checked?.valid || checked.no_changes || save.isPending} onClick={() => { if (view.revision) save.mutate({ revision: view.revision, content }); }}>{save.isPending ? "Saving safely…" : "Save file"}</Button>
            <Button className="button--quiet" disabled={save.isPending} onClick={close}>Close</Button>
          </div>
          {checked && !checked.valid && <ul className="raw-problems" aria-label="Validation problems">{checked.problems.map(problem => <li key={problem} className="error">{problem}</li>)}</ul>}
          {checked?.valid && (checked.no_changes
            ? <p className="muted-note">Nothing has changed yet.</p>
            : <p className="success" role="status">
                Checks passed.
                {checked.changed_known.length > 0 && ` Changes ${checked.changed_known.map(change => change.label).join(", ")}.`}
                {checked.removed_known.length > 0 && ` Removes ${checked.removed_known.join(", ")}.`}
                {checked.other_lines_changed && " Other lines changed."}
                {checked.restart_required && " Takes effect after the server restarts."}
              </p>)}
          {(check.error || save.error) && <p className="error" role="alert">{check.error?.message ?? save.error?.message}</p>}
        </>)}
  </section>;
}

export function SettingsPanel({ profileId, running }: { profileId: string; running: boolean }) {
  const cache = useQueryClient();
  const settings = useQuery({ queryKey: ["settings", profileId], queryFn: () => api<SettingsView>(`/profiles/${profileId}/settings`) });
  const view = settings.data;
  const [draft, setDraft] = useState<Record<string, DraftValue>>({});
  const [search, setSearch] = useState("");
  const [reviewRequest, setReviewRequest] = useState<{ revision: string; changes: SettingChange[] } | null>(null);
  const [notice, setNotice] = useState("");
  const [localError, setLocalError] = useState("");
  useEffect(() => { if (view) { setDraft(draftFor(view)); setReviewRequest(null); } }, [profileId, view]);

  function request(): { revision: string; changes: SettingChange[] } | null {
    if (!view?.revision) return null;
    const changes: SettingChange[] = [];
    for (const entry of view.settings) {
      const raw = draft[entry.key];
      let value: string | number | boolean;
      if (entry.type === "integer") {
        value = Number(raw);
        if (!Number.isInteger(value)) { setLocalError(`${entry.label} must be a whole number.`); return null; }
      } else value = entry.type === "boolean" ? raw === true : String(raw ?? "");
      if (value !== entry.value) changes.push({ key: entry.key, value });
    }
    if (!changes.length) { setLocalError("Change at least one setting before reviewing."); return null; }
    setLocalError("");
    return { revision: view.revision, changes };
  }

  const preview = useMutation({
    mutationFn: (payload: { revision: string; changes: SettingChange[] }) => api<SettingsPreview>(`/profiles/${profileId}/settings/preview`, { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: (_, payload) => setReviewRequest(payload),
  });
  const apply = useMutation({
    mutationFn: (payload: { revision: string; changes: SettingChange[] }) => api<SettingsApplyResult>(`/profiles/${profileId}/settings`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: result => {
      cache.setQueryData(["settings", profileId], result.view);
      setDraft(draftFor(result.view));
      setReviewRequest(null);
      preview.reset();
      setNotice(`Settings saved. Recovery snapshot ${result.snapshot_name} was created.${running && result.restart_required ? " Restart the server when convenient to apply them." : ""}`);
    },
    onError: () => void cache.invalidateQueries({ queryKey: ["settings", profileId] }),
  });
  function update(key: string, value: DraftValue) { setDraft(current => ({ ...current, [key]: value })); setNotice(""); setReviewRequest(null); preview.reset(); }
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!view || !term) return view?.settings ?? [];
    return view.settings.filter(entry => `${entry.label} ${entry.description} ${entry.key} ${entry.category}`.toLowerCase().includes(term));
  }, [search, view]);

  if (!view) return <section className="card"><p className="empty-note">Loading settings…</p></section>;
  if (!view.present) return <section className="card"><p className="eyebrow">server.properties</p><h2>Server settings</h2><p className="empty-note">No readable server.properties file was found in this profile folder.</p></section>;
  return <section className="card settings-editor" id="settings">
    <div className="section-heading"><div><p className="eyebrow">server.properties</p><h2>Guided settings</h2></div><span>Recovery protected</span></div>
    <p className="muted-note">Change common settings with validation and review the exact diff before Blockstead writes anything.</p>
    <label className="settings-search">Search settings<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Players, difficulty, port…" /></label>
    <div className="settings-groups">{categories.map(category => {
      const entries = filtered.filter(entry => entry.category === category);
      if (!entries.length) return null;
      return <section className="settings-group" key={category}><h3>{category}</h3><div>{entries.map(entry => <article className="setting-field" key={entry.key}>
        <div><strong>{entry.label}</strong><p>{entry.description}</p><code>{entry.key}</code></div>
        <div>{inputFor(entry, draft[entry.key] ?? "", value => update(entry.key, value))}{entry.restart_required && <small>Restart required</small>}</div>
      </article>)}</div></section>;
    })}</div>
    {!filtered.length && <p className="empty-note">No guided settings match that search.</p>}
    {view.other_keys.length > 0 && <p className="muted-note">Preserved advanced keys: {view.other_keys.join(", ")}.</p>}
    {(localError || preview.error?.message) && <p className="error" role="alert">{localError || preview.error?.message}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    <div className="settings-actions"><Button className="button--secondary" disabled={preview.isPending || apply.isPending} onClick={() => { const payload = request(); if (payload) preview.mutate(payload); }}>{preview.isPending ? "Checking…" : "Review changes"}</Button></div>
    {preview.data && reviewRequest && <section className="settings-review" aria-label="Settings change review"><div className="section-heading"><div><p className="eyebrow">Confirm changes</p><h3>Review before saving</h3></div><span>{preview.data.changes.length} change{preview.data.changes.length === 1 ? "" : "s"}</span></div>
      <ul>{preview.data.changes.map(change => <li key={change.key}><div><strong>{change.label}</strong><code>{change.key}</code></div><span><del>{shown(change.before)}</del><b aria-hidden="true">→</b><ins>{shown(change.after)}</ins></span></li>)}</ul>
      {preview.data.restart_required && <p className="warning">These changes take effect after the server restarts. Saving them will not restart it automatically.</p>}
      {apply.error && <p className="error" role="alert">{apply.error.message}</p>}
      <div className="settings-actions"><Button disabled={apply.isPending} onClick={() => apply.mutate(reviewRequest)}>{apply.isPending ? "Saving safely…" : "Apply changes"}</Button><Button className="button--quiet" disabled={apply.isPending} onClick={() => { setReviewRequest(null); preview.reset(); }}>Keep editing</Button></div>
    </section>}
    <p className="muted-note">Comments, unknown keys, and ordering are preserved. Every write creates a private recovery snapshot.</p>
    <RawEditor profileId={profileId} onSaved={result => {
      cache.setQueryData(["settings", profileId], result.view);
      setNotice(`Raw file saved. Recovery snapshot ${result.snapshot_name} was created.${running && result.restart_required ? " Restart the server when convenient to apply it." : ""}`);
    }} />
  </section>;
}
