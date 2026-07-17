import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CatalogProject, type CatalogSearch, type ModpackInstallResult } from "../../api/client";
import { Button } from "../../components/Button";

function directoryFrom(value: string) { return value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64) || "modpack"; }

export function ModpacksPanel({ stopped, onCreated }: { stopped: boolean; onCreated: (profileId: string) => void }) {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [chosen, setChosen] = useState<CatalogProject | null>(null);
  const [name, setName] = useState("");
  const [directory, setDirectory] = useState("");
  const [notice, setNotice] = useState("");
  const results = useQuery({ queryKey: ["modpack-search", searched], queryFn: () => api<CatalogSearch>(`/modpacks/search?query=${encodeURIComponent(searched)}`), enabled: Boolean(searched) });
  const installed = async (result: ModpackInstallResult) => { await client.invalidateQueries({ queryKey: ["profiles"] }); onCreated(result.id); setNotice(`${result.name} is installed. Review its readiness, accept the EULA, then start it.`); setChosen(null); };
  const install = useMutation({ mutationFn: () => api<ModpackInstallResult>("/modpacks/install", { method: "POST", body: JSON.stringify({ name, directory_name: directory, project_id: chosen?.project_id }) }), onSuccess: result => { void installed(result); }, onError: error => setNotice(error.message) });
  const upload = useMutation({ mutationFn: (body: FormData) => api<ModpackInstallResult>("/modpacks/upload", { method: "POST", body }), onSuccess: result => { void installed(result); }, onError: error => setNotice(error.message) });
  function search(event: FormEvent) { event.preventDefault(); if (query.trim()) setSearched(query.trim()); }
  function choose(project: CatalogProject) { const title = project.title ?? project.slug ?? "Modpack"; setChosen(project); setName(title); setDirectory(directoryFrom(project.slug ?? title)); setNotice(""); }
  function uploadPack(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); const file = data.get("file"); if (!(file instanceof File) || !file.name) return; upload.mutate(data); form.reset(); }
  const busy = install.isPending || upload.isPending;
  return <section className="card" id="modpacks"><div className="section-heading"><div><p className="eyebrow">Complete modded setup</p><h2>Modpacks</h2></div><span>Powered by Modrinth</span></div><p className="muted-note">A modpack creates a new Fabric, Forge, Quilt, or NeoForge profile with its server files, configuration overrides, and exact declared loader version. Blockstead never accepts the EULA for you.</p><div className="modpack-tools"><div><h3>Browse modpacks</h3><form className="inline-form" onSubmit={search}><label>Search Modrinth modpacks<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Create, adventure, lightweight…" /></label><Button disabled={!stopped || !query.trim()}>Search</Button></form><div className="catalog-results">{results.data?.projects.map(project => <article key={project.project_id}><div><strong>{project.title ?? project.slug ?? project.project_id}</strong><p>{project.description}</p></div><Button className="button--secondary button--small" disabled={!stopped || busy} onClick={() => choose(project)}>Choose</Button></article>)}</div>{chosen && <form className="install-card" onSubmit={event => { event.preventDefault(); install.mutate(); }}><strong>Install {chosen.title ?? chosen.slug}</strong><label>Profile name<input value={name} onChange={event => setName(event.target.value)} required maxLength={80} /></label><label>Server folder<input value={directory} onChange={event => setDirectory(event.target.value)} pattern="[a-z0-9][a-z0-9_-]*" required maxLength={64} /></label><Button disabled={!stopped || busy}>{install.isPending ? "Installing…" : "Install modpack"}</Button></form>}</div><div><h3>Import a local .mrpack</h3><form className="upload-form" onSubmit={uploadPack}><label>Profile name<input name="name" required maxLength={80} /></label><label>Server folder<input name="directory_name" pattern="[a-z0-9][a-z0-9_-]*" required maxLength={64} placeholder="my-modpack" /></label><label>Modrinth pack file<input name="file" type="file" accept=".mrpack,application/zip" required /></label><Button disabled={!stopped || busy}>{upload.isPending ? "Importing…" : "Import pack"}</Button></form></div></div>{!stopped && <p className="muted-note">Stop the current server before installing a new modpack.</p>}{notice && <p className={notice.includes("is installed") ? "success" : "error"} role="status">{notice}</p>}</section>;
}
