import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CatalogSearch, type CatalogVersion, type ExtensionEntry, type ExtensionUpdate, type ExtensionUpdates, type ExtensionsView, type SharedMapView } from "../../api/client";
import { Button } from "../../components/Button";
import { formatBytes } from "../../lib/format";
import { SharedMapCard, SHARED_MAP_PROJECT_ID } from "./SharedMapCard";
import { ModConfigEditor } from "./ModConfigEditor";

const SORT_OPTIONS = [["relevance", "Relevance"], ["downloads", "Most downloaded"], ["follows", "Most followed"], ["newest", "Newest"], ["updated", "Recently updated"]] as const;
export type CatalogSource = "modrinth" | "hangar" | "curseforge";
const SOURCE_LABELS: Record<CatalogSource, string> = { modrinth: "Modrinth", hangar: "Hangar (PaperMC)", curseforge: "CurseForge" };

function VersionChooser({ profileId, projectId, source, locked, install }: { profileId: string; projectId: string; source: CatalogSource; locked: boolean; install: (versionId: string) => void }) {
  const versions = useQuery({ queryKey: ["extension-versions", profileId, source, projectId], queryFn: () => api<{ versions: CatalogVersion[] }>(`/profiles/${profileId}/catalog/versions?source=${source}&project_id=${encodeURIComponent(projectId)}`) });
  return <ul className="version-list">{versions.data?.versions.map(version => <li key={version.version_id}><div><strong>{version.version_number ?? version.version_id}</strong><small>{[version.version_type, version.date_published?.slice(0, 10), version.game_versions.length ? `MC ${version.game_versions.join(", ")}` : null, version.required_plugins?.length ? `needs ${version.required_plugins.join(", ")}` : null].filter(Boolean).join(" · ")}</small></div>{version.external_url ? <a className="button button--quiet button--small" href={version.external_url} target="_blank" rel="noreferrer">Get in browser</a> : <Button className="button--secondary button--small" disabled={locked} onClick={() => install(version.version_id)}>Install this version</Button>}</li>)}{versions.isFetching && <li className="empty-note">Loading versions…</li>}{versions.data && !versions.data.versions.length && <li className="empty-note">No compatible versions for this server.</li>}{versions.error && <li className="empty-note">{versions.error.message}</li>}</ul>;
}

function ExtensionRow({ entry, disabled, locked, act, update }: { entry: ExtensionEntry; disabled: boolean; locked: boolean; act: (kind: "toggle" | "remove" | "update", entry: ExtensionEntry, disabled: boolean) => void; update?: ExtensionUpdate }) {
  return <li className="extension-row"><div><strong>{entry.display_name ?? entry.file_name}</strong><span>{entry.version ? `v${entry.version} · ` : ""}{formatBytes(entry.size_bytes)} · {entry.kind.replace("-", " ")}</span><small>{entry.file_name}</small></div><div className="row-actions">{update && <Button className="button--small" disabled={locked} onClick={() => act("update", entry, disabled)}>Update to {update.new_version_number ?? "latest"}</Button>}<Button className="button--secondary button--small" disabled={locked} onClick={() => act("toggle", entry, disabled)}>{disabled ? "Enable" : "Disable"}</Button><Button className="button--quiet button--small" disabled={locked} onClick={() => act("remove", entry, disabled)}>Remove</Button></div></li>;
}

export function ExtensionsPanel({ profileId, stopped }: { profileId: string; stopped: boolean }) {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [notice, setNotice] = useState("");
  const [chosenCategories, setChosenCategories] = useState<string[]>([]);
  const [sort, setSort] = useState<string>("relevance");
  const [offset, setOffset] = useState(0);
  const [source, setSource] = useState<CatalogSource>("modrinth");
  const [versionsFor, setVersionsFor] = useState<string | null>(null);
  const inventory = useQuery({ queryKey: ["extensions", profileId], queryFn: () => api<ExtensionsView>(`/profiles/${profileId}/extensions`) });
  const sharedMap = useQuery({ queryKey: ["shared-map", profileId], queryFn: () => api<SharedMapView>(`/profiles/${profileId}/shared-map`) });
  const categories = useQuery({ queryKey: ["extension-categories", profileId, source], queryFn: () => api<{ categories: string[] }>(`/profiles/${profileId}/catalog/categories?source=${source}`), enabled: inventory.data?.directory != null, staleTime: Infinity });
  const results = useQuery({ queryKey: ["extension-search", profileId, source, searched, chosenCategories, sort, offset], queryFn: () => api<CatalogSearch>(`/profiles/${profileId}/catalog/search?source=${source}&query=${encodeURIComponent(searched)}&categories=${encodeURIComponent(chosenCategories.join(","))}&sort=${sort}&offset=${offset}`), enabled: Boolean(searched) });
  const updates = useQuery({ queryKey: ["extension-updates", profileId], queryFn: () => api<ExtensionUpdates>(`/profiles/${profileId}/extensions/updates`), enabled: false });
  const curseforge = useQuery({ queryKey: ["curseforge-settings"], queryFn: () => api<{ configured: boolean }>("/settings/curseforge"), enabled: source === "curseforge" });
  const refresh = () => { void client.invalidateQueries({ queryKey: ["extensions", profileId] }); if (updates.data) void updates.refetch(); };
  const keyAction = useMutation({
    mutationFn: async ({ endpoint, init }: { endpoint: string; init: RequestInit }) => api<unknown>(endpoint, init),
    onSuccess: () => { setNotice("CurseForge key updated."); void client.invalidateQueries({ queryKey: ["curseforge-settings"] }); },
    onError: error => setNotice(error.message),
  });
  const action = useMutation({
    mutationFn: async ({ endpoint, init }: { endpoint: string; init: RequestInit }) => api<unknown>(endpoint, init),
    onSuccess: () => { setNotice("Change saved. Restart the server before expecting it to take effect."); void refresh(); },
    onError: error => setNotice(error.message),
  });
  function manage(kind: "toggle" | "remove" | "update", entry: ExtensionEntry, disabled: boolean) {
    setNotice("");
    if (kind === "toggle") action.mutate({ endpoint: `/profiles/${profileId}/extensions/toggle`, init: { method: "POST", body: JSON.stringify({ file_name: entry.file_name, enabled: disabled }) } });
    else if (kind === "update") action.mutate({ endpoint: `/profiles/${profileId}/extensions/update`, init: { method: "POST", body: JSON.stringify({ file_name: entry.file_name }) } });
    else if (window.confirm(`Remove ${entry.file_name}? This cannot be undone.`)) action.mutate({ endpoint: `/profiles/${profileId}/extensions/${encodeURIComponent(entry.file_name)}?disabled=${disabled}`, init: { method: "DELETE" } });
  }
  function bulk(enabled: boolean) {
    setNotice("");
    action.mutate({ endpoint: `/profiles/${profileId}/extensions/toggle-all`, init: { method: "POST", body: JSON.stringify({ enabled }) } });
  }
  function search(event: FormEvent) { event.preventDefault(); if (query.trim()) { setOffset(0); setVersionsFor(null); setSearched(query.trim()); } }
  function toggleCategory(name: string) {
    setOffset(0);
    setChosenCategories(current => current.includes(name) ? current.filter(item => item !== name) : current.length < 5 ? [...current, name] : current);
  }
  function switchSource(next: CatalogSource) {
    setSource(next);
    setChosenCategories([]);
    setOffset(0);
    setVersionsFor(null);
  }
  function install(projectId: string, versionId?: string) {
    setNotice("");
    action.mutate({ endpoint: `/profiles/${profileId}/extensions/install`, init: { method: "POST", body: JSON.stringify({ project_id: projectId, source, ...(versionId ? { version_id: versionId } : {}) }) } });
  }
  function saveCurseForgeKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = new FormData(form).get("api_key");
    if (typeof value !== "string" || !value.trim()) return;
    setNotice("");
    keyAction.mutate({ endpoint: "/settings/curseforge", init: { method: "PUT", body: JSON.stringify({ api_key: value.trim() }) } });
    form.reset();
  }
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
  return <section className="card" id="extensions"><div className="section-heading"><div><p className="eyebrow">Mods and plugins</p><h2>Extensions</h2></div><span>{view ? `${view.entries.length} active · ${view.disabled_entries.length} disabled` : "Loading"}</span></div>{unsupported ? <p className="empty-note">Vanilla does not load mod jars. Create a Fabric, Forge, Quilt, or NeoForge profile for mods.</p> : <>{view && <SharedMapCard entries={view.entries} disabledEntries={view.disabled_entries} map={sharedMap.data} stopped={stopped} busy={action.isPending} install={() => action.mutate({ endpoint: `/profiles/${profileId}/extensions/install`, init: { method: "POST", body: JSON.stringify({ project_id: SHARED_MAP_PROJECT_ID }) } })} />}{view?.warnings.map(warning => <div className="warning" key={`${warning.code}-${warning.files.join()}`}><strong>{warning.code.replace("-", " ")}</strong><span>{warning.message}</span><small>{warning.files.join(", ")}</small></div>)}{view && (view.entries.length > 0 || view.disabled_entries.length > 0) && <div className="vanilla-switch"><div><strong>Vanilla switch</strong><span>{view.entries.length ? `Turn all ${view.entries.length} ${view.directory === "plugins" ? "plugins" : "mods"} off at once to play plain Minecraft. Nothing is deleted, and everything can come back with one click.` : "Everything is off — the server plays like plain Minecraft. Bring it all back whenever you like."}</span></div><div className="row-actions">{view.entries.length > 0 && <Button className="button--secondary button--small" disabled={!stopped || action.isPending} onClick={() => bulk(false)}>Disable all</Button>}{view.disabled_entries.length > 0 && <Button className="button--secondary button--small" disabled={!stopped || action.isPending} onClick={() => bulk(true)}>Enable all</Button>}</div></div>}<div className="extension-columns"><div><div className="list-heading"><h3>Installed</h3><Button className="button--quiet button--small" disabled={!view?.entries.length || updates.isFetching} onClick={() => { setNotice(""); void updates.refetch(); }}>{updates.isFetching ? "Checking…" : "Check for updates"}</Button></div>{updates.data && !updates.isFetching && <p className="update-summary">{updates.data.updates.length ? `${updates.data.updates.length} update${updates.data.updates.length === 1 ? "" : "s"} available.` : "Everything Modrinth recognizes is up to date."}{updates.data.unknown.length ? ` ${updates.data.unknown.length} file${updates.data.unknown.length === 1 ? " was" : "s were"} not matched to Modrinth.` : ""}</p>}<ul className="extension-list">{view?.entries.map(entry => <ExtensionRow key={entry.file_name} entry={entry} disabled={false} locked={!stopped || action.isPending} act={manage} update={updates.data?.updates.find(item => item.file_name === entry.file_name)} />)}{view && !view.entries.length && <li className="empty-note">No active files in {view.directory}/.</li>}</ul></div><div><h3>Disabled</h3><ul className="extension-list">{view?.disabled_entries.map(entry => <ExtensionRow key={entry.file_name} entry={entry} disabled locked={!stopped || action.isPending} act={manage} />)}{view && !view.disabled_entries.length && <li className="empty-note">Nothing is disabled.</li>}</ul></div></div><div className="catalog-tools"><div><h3>Browse catalogs</h3><form className="inline-form" onSubmit={search}><label>Search server-compatible projects<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Lithium, LuckPerms…" /></label><Button disabled={!stopped || !query.trim()}>Search</Button></form><div className="catalog-filters"><label>Catalog<select value={source} onChange={event => switchSource(event.target.value as CatalogSource)}>{(Object.keys(SOURCE_LABELS) as CatalogSource[]).filter(key => key !== "hangar" || view?.directory === "plugins").map(key => <option key={key} value={key}>{SOURCE_LABELS[key]}</option>)}</select></label><label>Sort by<select value={sort} onChange={event => { setSort(event.target.value); setOffset(0); }}>{SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>{Boolean(categories.data?.categories?.length) && <div className="category-chips" role="group" aria-label="Category filters">{categories.data?.categories.map(name => <button key={name} type="button" className={chosenCategories.includes(name) ? "chip chip--on" : "chip"} aria-pressed={chosenCategories.includes(name)} onClick={() => toggleCategory(name)}>{name.replace(/[_-]/g, " ")}</button>)}</div>}</div>{source === "curseforge" && curseforge.data && !curseforge.data.configured && <form className="inline-form curseforge-key-form" onSubmit={saveCurseForgeKey}><label>CurseForge API key<input name="api_key" type="password" required minLength={8} placeholder="Paste your key" /></label><Button disabled={keyAction.isPending}>Save key</Button><p className="empty-note">Searching CurseForge needs your own free API key from console.curseforge.com. Blockstead stores it on this computer only and never shows it again.</p></form>}{source === "curseforge" && curseforge.data?.configured && <p className="empty-note">A CurseForge key is saved on this computer. <Button className="button--quiet button--small" disabled={keyAction.isPending} onClick={() => { setNotice(""); keyAction.mutate({ endpoint: "/settings/curseforge", init: { method: "DELETE" } }); }}>Remove key</Button></p>}{results.isFetching && <p className="empty-note">Searching {SOURCE_LABELS[source]}…</p>}<div className="catalog-results">{results.data?.projects.map(project => <article key={project.project_id}><div><strong>{project.title ?? project.slug ?? project.project_id}</strong><p>{project.description}</p><small>{project.author ? `by ${project.author} · ` : ""}{project.downloads?.toLocaleString() ?? "—"} downloads{project.page_url ? <> · <a href={project.page_url} target="_blank" rel="noreferrer">project page</a></> : null}</small>{versionsFor === project.project_id && <VersionChooser profileId={profileId} projectId={project.project_id} source={source} locked={!stopped || action.isPending} install={versionId => install(project.project_id, versionId)} />}</div><div className="row-actions">{project.installable === false ? <a className="button button--secondary button--small" href={project.page_url ?? undefined} target="_blank" rel="noreferrer">Get in browser</a> : <Button className="button--secondary button--small" disabled={!stopped || action.isPending} onClick={() => install(project.project_id)}>Install</Button>}<Button className="button--quiet button--small" onClick={() => setVersionsFor(versionsFor === project.project_id ? null : project.project_id)}>{versionsFor === project.project_id ? "Hide versions" : "Versions"}</Button></div></article>)}{results.data && !results.data.projects.length && <p className="empty-note">Nothing matched. Try a different search or fewer filters.</p>}</div>{results.data && (results.data.total ?? 0) > (results.data.limit ?? 20) && <div className="pager"><Button className="button--quiet button--small" disabled={offset === 0 || results.isFetching} onClick={() => { setVersionsFor(null); setOffset(Math.max(0, offset - (results.data?.limit ?? 20))); }}>Previous</Button><span>{offset + 1}–{Math.min(offset + (results.data.limit ?? 20), results.data.total ?? 0)} of {results.data.total?.toLocaleString()}</span><Button className="button--quiet button--small" disabled={offset + (results.data.limit ?? 20) >= (results.data.total ?? 0) || results.isFetching} onClick={() => { setVersionsFor(null); setOffset(offset + (results.data?.limit ?? 20)); }}>Next</Button></div>}</div><div><h3>Upload a jar</h3><form className="upload-form" onSubmit={upload}><label>Local .jar file<input name="file" type="file" accept=".jar,application/java-archive" required /></label><Button disabled={!stopped || action.isPending}>Upload</Button></form></div></div><ModConfigEditor profileId={profileId} stopped={stopped} /></>}{!stopped && !unsupported && <p className="muted-note">Stop the server before changing extension files.</p>}{notice && <p className={notice.startsWith("Change saved") ? "success" : "error"} role="status">{notice}</p>}</section>;
}
