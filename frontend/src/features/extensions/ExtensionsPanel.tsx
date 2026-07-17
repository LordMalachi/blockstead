import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CatalogSearch, type ExtensionEntry, type ExtensionsView } from "../../api/client";
import { Button } from "../../components/Button";
import { formatBytes } from "../../lib/format";
import { SharedMapCard, SHARED_MAP_PROJECT_ID } from "./SharedMapCard";
import { ModConfigEditor } from "./ModConfigEditor";

function ExtensionRow({ entry, disabled, locked, act }: { entry: ExtensionEntry; disabled: boolean; locked: boolean; act: (kind: "toggle" | "remove", entry: ExtensionEntry, disabled: boolean) => void }) {
  return <li className="extension-row"><div><strong>{entry.display_name ?? entry.file_name}</strong><span>{entry.version ? `v${entry.version} · ` : ""}{formatBytes(entry.size_bytes)} · {entry.kind.replace("-", " ")}</span><small>{entry.file_name}</small></div><div className="row-actions"><Button className="button--secondary button--small" disabled={locked} onClick={() => act("toggle", entry, disabled)}>{disabled ? "Enable" : "Disable"}</Button><Button className="button--quiet button--small" disabled={locked} onClick={() => act("remove", entry, disabled)}>Remove</Button></div></li>;
}

export function ExtensionsPanel({ profileId, stopped }: { profileId: string; stopped: boolean }) {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [notice, setNotice] = useState("");
  const inventory = useQuery({ queryKey: ["extensions", profileId], queryFn: () => api<ExtensionsView>(`/profiles/${profileId}/extensions`) });
  const results = useQuery({ queryKey: ["extension-search", profileId, searched], queryFn: () => api<CatalogSearch>(`/profiles/${profileId}/modrinth/search?query=${encodeURIComponent(searched)}`), enabled: Boolean(searched) });
  const refresh = () => client.invalidateQueries({ queryKey: ["extensions", profileId] });
  const action = useMutation({
    mutationFn: async ({ endpoint, init }: { endpoint: string; init: RequestInit }) => api<unknown>(endpoint, init),
    onSuccess: () => { setNotice("Change saved. Restart the server before expecting it to take effect."); void refresh(); },
    onError: error => setNotice(error.message),
  });
  function manage(kind: "toggle" | "remove", entry: ExtensionEntry, disabled: boolean) {
    setNotice("");
    if (kind === "toggle") action.mutate({ endpoint: `/profiles/${profileId}/extensions/toggle`, init: { method: "POST", body: JSON.stringify({ file_name: entry.file_name, enabled: disabled }) } });
    else if (window.confirm(`Remove ${entry.file_name}? This cannot be undone.`)) action.mutate({ endpoint: `/profiles/${profileId}/extensions/${encodeURIComponent(entry.file_name)}?disabled=${disabled}`, init: { method: "DELETE" } });
  }
  function search(event: FormEvent) { event.preventDefault(); if (query.trim()) setSearched(query.trim()); }
  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || !file.name) return;
    const body = new FormData(); body.set("file", file);
    action.mutate({ endpoint: `/profiles/${profileId}/extensions/upload`, init: { method: "POST", body } });
    form.reset();
  }
  const view = inventory.data;
  const unsupported = view?.directory == null;
  return <section className="card" id="extensions"><div className="section-heading"><div><p className="eyebrow">Mods and plugins</p><h2>Extensions</h2></div><span>{view ? `${view.entries.length} active · ${view.disabled_entries.length} disabled` : "Loading"}</span></div>{unsupported ? <p className="empty-note">Vanilla does not load mod jars. Create a Fabric, Forge, Quilt, or NeoForge profile for mods.</p> : <>{view && <SharedMapCard entries={view.entries} disabledEntries={view.disabled_entries} stopped={stopped} busy={action.isPending} install={() => action.mutate({ endpoint: `/profiles/${profileId}/extensions/install`, init: { method: "POST", body: JSON.stringify({ project_id: SHARED_MAP_PROJECT_ID }) } })} />}{view?.warnings.map(warning => <div className="warning" key={`${warning.code}-${warning.files.join()}`}><strong>{warning.code.replace("-", " ")}</strong><span>{warning.message}</span><small>{warning.files.join(", ")}</small></div>)}<div className="extension-columns"><div><h3>Installed</h3><ul className="extension-list">{view?.entries.map(entry => <ExtensionRow key={entry.file_name} entry={entry} disabled={false} locked={!stopped || action.isPending} act={manage} />)}{view && !view.entries.length && <li className="empty-note">No active files in {view.directory}/.</li>}</ul></div><div><h3>Disabled</h3><ul className="extension-list">{view?.disabled_entries.map(entry => <ExtensionRow key={entry.file_name} entry={entry} disabled locked={!stopped || action.isPending} act={manage} />)}{view && !view.disabled_entries.length && <li className="empty-note">Nothing is disabled.</li>}</ul></div></div><div className="catalog-tools"><div><h3>Browse Modrinth</h3><form className="inline-form" onSubmit={search}><label>Search server-compatible projects<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Lithium, LuckPerms…" /></label><Button disabled={!stopped || !query.trim()}>Search</Button></form>{results.isFetching && <p className="empty-note">Searching Modrinth…</p>}<div className="catalog-results">{results.data?.projects.map(project => <article key={project.project_id}><div><strong>{project.title ?? project.slug ?? project.project_id}</strong><p>{project.description}</p><small>{project.author ? `by ${project.author} · ` : ""}{project.downloads?.toLocaleString() ?? "—"} downloads</small></div><Button className="button--secondary button--small" disabled={!stopped || action.isPending} onClick={() => action.mutate({ endpoint: `/profiles/${profileId}/extensions/install`, init: { method: "POST", body: JSON.stringify({ project_id: project.project_id }) } })}>Install</Button></article>)}</div></div><div><h3>Upload a jar</h3><form className="upload-form" onSubmit={upload}><label>Local .jar file<input name="file" type="file" accept=".jar,application/java-archive" required /></label><Button disabled={!stopped || action.isPending}>Upload</Button></form></div></div><ModConfigEditor profileId={profileId} stopped={stopped} /></>}{!stopped && !unsupported && <p className="muted-note">Stop the server before changing extension files.</p>}{notice && <p className={notice.startsWith("Change saved") ? "success" : "error"} role="status">{notice}</p>}</section>;
}
