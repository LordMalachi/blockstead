import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ProvisionResult, type ProvisionVersions } from "../../api/client";
import { Button } from "../../components/Button";
import { FieldNotice, useFieldErrors } from "../../components/FieldError";
import { describeServerDirectoryName, normalizeServerDirectoryName } from "../../lib/server-directory";

const loaderOptions = [
  { value: "vanilla", label: "Vanilla", detail: "Official Minecraft server" },
  { value: "fabric", label: "Fabric", detail: "Lightweight mod loader" },
  { value: "forge", label: "Forge", detail: "Long-running mod ecosystem" },
  { value: "quilt", label: "Quilt", detail: "Fabric-derived mod loader" },
  { value: "neoforge", label: "NeoForge", detail: "Modern Forge-derived loader" },
  { value: "paper", label: "Paper", detail: "Plugin server (optional)" },
];

export function ProvisionPanel({ stopped, onCreated }: { stopped: boolean; onCreated: (profileId: string) => void }) {
  const client = useQueryClient();
  const [distribution, setDistribution] = useState("vanilla");
  const [version, setVersion] = useState("");
  const [loaderVersion, setLoaderVersion] = useState("");
  const [name, setName] = useState("Family Server");
  const [directory, setDirectory] = useState("family-server");
  const [notice, setNotice] = useState("");
  const fieldErrors = useFieldErrors();
  const versions = useQuery({ queryKey: ["provision-versions", distribution], queryFn: () => api<ProvisionVersions>(`/provision/versions/${distribution}`) });
  useEffect(() => { const available = versions.data?.versions; if (available?.length) setVersion(current => available.includes(current) ? current : available[0]); }, [versions.data]);
  // Live-check the folder name as the owner types, so an invalid value shows its
  // suggestion immediately instead of only after submit or on blur.
  function changeDirectory(value: string) {
    setDirectory(value);
    fieldErrors.setField("directory_name", describeServerDirectoryName(value));
  }
  const create = useMutation({
    mutationFn: () => api<ProvisionResult>("/provision", { method: "POST", body: JSON.stringify({ name, directory_name: normalizeServerDirectoryName(directory), distribution, minecraft_version: version, loader_version: loaderVersion || null }) }),
    onSuccess: async result => { await client.invalidateQueries({ queryKey: ["profiles"] }); fieldErrors.clear(); setNotice(`${result.name} is ready for EULA review.`); onCreated(result.id); },
    onError: error => { setNotice(error.message); fieldErrors.setFromError(error); },
  });
  function submit(event: FormEvent) { event.preventDefault(); setNotice(""); create.mutate(); }
  const nameError = fieldErrors.get("name");
  const directoryError = fieldErrors.get("directory_name");
  return <section className="card onboarding-card" id="create-server">
    <div className="section-heading"><div><p className="eyebrow">New server</p><h2>Create a configured profile</h2></div><span>Official sources</span></div>
    <p>Choose a Minecraft server type. Blockstead downloads the matching server and loader, verifies published checksums when available, and keeps each profile in its own folder.</p>
    <p className="muted-note"><strong>A new profile always starts with a blank world.</strong> To keep an existing vanilla world, open that server’s <strong>Maintenance</strong> workspace and choose <strong>Create a modded copy</strong>; Blockstead reviews, protects, and transfers the world into the new server. <a href="/servers">Choose an existing server</a>.</p>
    <form className="provision-form" onSubmit={submit}>
      <label>Server type<select value={distribution} onChange={event => { setDistribution(event.target.value); setVersion(""); setLoaderVersion(""); }} aria-label="Server type">{loaderOptions.map(option => <option key={option.value} value={option.value}>{option.label} — {option.detail}</option>)}</select></label>
      <label>Minecraft version<select value={version} onChange={event => setVersion(event.target.value)} disabled={versions.isLoading || !versions.data?.versions.length} aria-label="Minecraft version"><option value="">{versions.isLoading ? "Loading versions…" : "Choose a version"}</option>{versions.data?.versions.map(item => <option value={item} key={item}>{item}</option>)}</select></label>
      <label>Profile name<input value={name} onChange={event => { setName(event.target.value); if (!directory || directory === normalizeServerDirectoryName(name)) changeDirectory(normalizeServerDirectoryName(event.target.value)); }} required maxLength={80} {...fieldErrors.controlProps("name")} /></label>
      {nameError && <FieldNotice id={fieldErrors.noticeId("name")} error={nameError} onUseSuggestion={value => setName(value)} />}
      <label>Server folder<input value={directory} onChange={event => changeDirectory(event.target.value)} onBlur={() => changeDirectory(normalizeServerDirectoryName(directory))} pattern="[a-z0-9][a-z0-9_-]*" required maxLength={64} {...fieldErrors.controlProps("directory_name")} /></label>
      {directoryError && <FieldNotice id={fieldErrors.noticeId("directory_name")} error={directoryError} onUseSuggestion={value => changeDirectory(value)} />}
      {distribution !== "vanilla" && distribution !== "paper" && <label>Loader version <span className="optional">optional</span><input value={loaderVersion} onChange={event => setLoaderVersion(event.target.value)} placeholder="Recommended/latest" pattern="[0-9A-Za-z][0-9A-Za-z.+_-]*" maxLength={64} /></label>}
      <div className="provision-submit"><Button disabled={!stopped || !version || create.isPending}>{create.isPending ? "Creating server…" : "Create server"}</Button><small>The Minecraft EULA is never accepted automatically.</small></div>
    </form>
    {!stopped && <p className="muted-note">Stop the active server before creating another profile.</p>}
    {versions.error && <p className="error" role="alert">{versions.error.message}</p>}
    {notice && <p className={notice.includes("ready") ? "success" : "error"} role="status">{notice}</p>}
  </section>;
}
