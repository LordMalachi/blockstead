import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ProvisionResult, type ProvisionVersions } from "../../api/client";
import { Button } from "../../components/Button";

const loaderOptions = [
  { value: "vanilla", label: "Vanilla", detail: "Official Minecraft server" },
  { value: "fabric", label: "Fabric", detail: "Lightweight mod loader" },
  { value: "forge", label: "Forge", detail: "Long-running mod ecosystem" },
  { value: "quilt", label: "Quilt", detail: "Fabric-derived mod loader" },
  { value: "neoforge", label: "NeoForge", detail: "Modern Forge-derived loader" },
  { value: "paper", label: "Paper", detail: "Plugin server (optional)" },
];

function folderFrom(value: string) { return value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64) || "minecraft-server"; }

export function ProvisionPanel({ stopped, onCreated }: { stopped: boolean; onCreated: (profileId: string) => void }) {
  const client = useQueryClient();
  const [distribution, setDistribution] = useState("vanilla");
  const [version, setVersion] = useState("");
  const [loaderVersion, setLoaderVersion] = useState("");
  const [name, setName] = useState("Family Server");
  const [directory, setDirectory] = useState("family-server");
  const [notice, setNotice] = useState("");
  const versions = useQuery({ queryKey: ["provision-versions", distribution], queryFn: () => api<ProvisionVersions>(`/provision/versions/${distribution}`) });
  useEffect(() => { const available = versions.data?.versions; if (available?.length) setVersion(current => available.includes(current) ? current : available[0]); }, [versions.data]);
  const create = useMutation({
    mutationFn: () => api<ProvisionResult>("/provision", { method: "POST", body: JSON.stringify({ name, directory_name: directory, distribution, minecraft_version: version, loader_version: loaderVersion || null }) }),
    onSuccess: async result => { await client.invalidateQueries({ queryKey: ["profiles"] }); setNotice(`${result.name} is ready for EULA review.`); onCreated(result.id); },
    onError: error => setNotice(error.message),
  });
  function submit(event: FormEvent) { event.preventDefault(); setNotice(""); create.mutate(); }
  return <section className="card onboarding-card" id="create-server">
    <div className="section-heading"><div><p className="eyebrow">New server</p><h2>Create a configured profile</h2></div><span>Official sources</span></div>
    <p>Choose a Minecraft server type. Blockstead downloads the matching server and loader, verifies published checksums when available, and keeps each profile in its own folder.</p>
    <form className="provision-form" onSubmit={submit}>
      <label>Server type<select value={distribution} onChange={event => { setDistribution(event.target.value); setVersion(""); setLoaderVersion(""); }} aria-label="Server type">{loaderOptions.map(option => <option key={option.value} value={option.value}>{option.label} — {option.detail}</option>)}</select></label>
      <label>Minecraft version<select value={version} onChange={event => setVersion(event.target.value)} disabled={versions.isLoading || !versions.data?.versions.length} aria-label="Minecraft version"><option value="">{versions.isLoading ? "Loading versions…" : "Choose a version"}</option>{versions.data?.versions.map(item => <option value={item} key={item}>{item}</option>)}</select></label>
      <label>Profile name<input value={name} onChange={event => { setName(event.target.value); if (!directory || directory === folderFrom(name)) setDirectory(folderFrom(event.target.value)); }} required maxLength={80} /></label>
      <label>Server folder<input value={directory} onChange={event => setDirectory(event.target.value)} pattern="[a-z0-9][a-z0-9_-]*" required maxLength={64} /></label>
      {distribution !== "vanilla" && distribution !== "paper" && <label>Loader version <span className="optional">optional</span><input value={loaderVersion} onChange={event => setLoaderVersion(event.target.value)} placeholder="Recommended/latest" pattern="[0-9A-Za-z][0-9A-Za-z.+_-]*" maxLength={64} /></label>}
      <div className="provision-submit"><Button disabled={!stopped || !version || create.isPending}>{create.isPending ? "Creating server…" : "Create server"}</Button><small>The Minecraft EULA is never accepted automatically.</small></div>
    </form>
    {!stopped && <p className="muted-note">Stop the active server before creating another profile.</p>}
    {versions.error && <p className="error" role="alert">{versions.error.message}</p>}
    {notice && <p className={notice.includes("ready") ? "success" : "error"} role="status">{notice}</p>}
  </section>;
}
