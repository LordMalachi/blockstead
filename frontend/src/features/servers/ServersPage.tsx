import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiUpload, type ImportScan, type ImportUploadResult, type ImportUploadStartResult, type PlayersView, type ProcessState, type Profile, type Schedule } from "../../api/client";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import { formatBytes } from "../../lib/format";
import { uploadBatches } from "../../lib/upload";
import { ModpacksPanel } from "../extensions/ModpacksPanel";
import { FirstServerChooser, type FirstServerPath } from "./FirstServerChooser";
import { scopeFor, type ServerScope } from "./scope";
import { ProvisionPanel } from "./ProvisionPanel";

function folderFrom(value: string) { return value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64) || "minecraft-server"; }

const folderInputProps: Record<string, string> = { webkitdirectory: "" };

function nextScheduled(schedule: Schedule | undefined): string {
  if (!schedule?.enabled) return "No schedule";
  const now = new Date();
  const minutesNow = now.getHours() * 60 + now.getMinutes();
  const upcoming = [{ label: "Start", time: schedule.start_time }, { label: "Stop", time: schedule.stop_time }]
    .filter((entry): entry is { label: string; time: string } => Boolean(entry.time))
    .map(entry => { const [hours, minutes] = entry.time.split(":").map(Number); return { ...entry, wait: (hours * 60 + minutes - minutesNow + 1440) % 1440 }; })
    .sort((a, b) => a.wait - b.wait)[0];
  return upcoming ? `${upcoming.label} ${upcoming.time}` : "No schedule";
}

function ServerCard({ scope, allowlist, schedule, onAction }: { scope: ServerScope; allowlist: number | null; schedule: Schedule | undefined; onAction: (endpoint: string, body?: object) => void }) {
  const { profile } = scope;
  return <article className="server-card">
    <div className="server-card__head">
      <div><h3><Link to={`/servers/${profile.id}/overview`}>{profile.name}</Link></h3><p>{profile.distribution}{profile.loader_version ? ` ${profile.loader_version}` : ""} · {profile.minecraft_version ?? "version unknown"}</p></div>
      <StatusBadge state={scope.state} />
    </div>
    <dl className="server-card__facts">
      <div><dt>Allowlist</dt><dd>{allowlist ?? "—"}</dd></div>
      <div><dt>Next schedule</dt><dd>{nextScheduled(schedule)}</dd></div>
      <div><dt>Last backup</dt><dd>No history yet</dd></div>
    </dl>
    <div className="server-card__actions">
      {scope.isActive && ["RUNNING", "STARTING", "DEGRADED"].includes(scope.state)
        ? <Button className="button--secondary" onClick={() => onAction("/server/stop")}>Stop safely</Button>
        : <Button disabled={!scope.canStart} onClick={() => onAction("/server/start", { profile_id: profile.id, mode: "normal" })}>Start server</Button>}
      <Link className="button button--quiet" to={`/servers/${profile.id}/overview`}>Open workspace</Link>
    </div>
    {scope.occupant && <small className="muted-note">{scope.reason}</small>}
  </article>;
}

export function ServersPage() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [path, setPath] = useState("");
  const [importName, setImportName] = useState("My Server");
  const [firstServerPath, setFirstServerPath] = useState<FirstServerPath>("create");
  const [scan, setScan] = useState<ImportScan | null>(null);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state"), refetchInterval: 1000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: () => api<Schedule[]>("/schedules") });
  const rosters = useQueries({
    queries: (profiles.data ?? []).map(profile => ({ queryKey: ["players", profile.id], queryFn: () => api<PlayersView>(`/profiles/${profile.id}/players`) })),
  });
  const action = useMutation({
    mutationFn: ({ endpoint, body }: { endpoint: string; body?: object }) => api<unknown>(endpoint, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: () => { setNotice(""); void client.invalidateQueries(); },
    onError: error => setNotice(error.message),
  });

  async function doScan(event: FormEvent) {
    event.preventDefault(); setNotice("");
    try { setScan(await api<ImportScan>("/imports/scan", { method: "POST", body: JSON.stringify({ path }) })); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Scan failed."); }
  }
  async function uploadFolder(event: FormEvent) {
    event.preventDefault(); setNotice("");
    if (!uploadFiles.length) return;
    const totalBytes = uploadFiles.reduce((sum, file) => sum + file.size, 0) || 1;
    const base = folderFrom(uploadFiles[0].webkitRelativePath.split("/")[0] || importName);
    setUploadProgress(0);
    let uploadId = "";
    try {
      let directory = base;
      let started: ImportUploadStartResult | null = null;
      for (let attempt = 1; attempt <= 5 && !started; attempt += 1) {
        directory = attempt === 1 ? base : `${base}-${attempt}`;
        try { started = await api<ImportUploadStartResult>("/imports/uploads", { method: "POST", body: JSON.stringify({ directory_name: directory }) }); }
        catch (error) {
          if (attempt === 5 || !(error instanceof Error) || !error.message.includes("already exists")) throw error;
        }
      }
      if (!started) throw new Error("The upload could not start.");
      uploadId = started.upload_id;
      let doneBytes = 0;
      for (const batch of uploadBatches(uploadFiles)) {
        const form = new FormData();
        for (const file of batch) form.append("files", file, file.webkitRelativePath || file.name);
        const batchBytes = batch.reduce((sum, file) => sum + file.size, 0);
        await apiUpload(`/imports/uploads/${uploadId}/files`, form, (loaded, total) => {
          setUploadProgress(Math.min(1, (doneBytes + batchBytes * (loaded / total)) / totalBytes));
        });
        doneBytes += batchBytes;
        setUploadProgress(Math.min(1, doneBytes / totalBytes));
      }
      const created = await api<ImportUploadResult>(`/imports/uploads/${uploadId}/finish`, { method: "POST", body: JSON.stringify({ name: importName, directory_name: directory }) });
      await client.invalidateQueries({ queryKey: ["profiles"] });
      void navigate(`/servers/${created.id}/overview`);
    } catch (error) {
      if (uploadId) void api(`/imports/uploads/${uploadId}`, { method: "DELETE" }).catch(() => undefined);
      setUploadProgress(null);
      setNotice(error instanceof Error ? error.message : "The import upload failed.");
    }
  }
  async function importProfile() {
    if (!scan) return;
    try {
      const created = await api<{ id: string }>("/profiles", { method: "POST", body: JSON.stringify({ name: importName, path: scan.canonical_path }) });
      setScan(null);
      await client.invalidateQueries({ queryKey: ["profiles"] });
      void navigate(`/servers/${created.id}/overview`);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Import failed."); }
  }

  const list = profiles.data ?? [];
  const snapshot = state.data ?? { state: "UNKNOWN" as const, pid: null, exit_code: null, reason: "Checking server state" };
  const hostFree = ["STOPPED", "CRASHED"].includes(snapshot.state);

  return <>
    <section className="page-head">
      <div><p className="eyebrow">Your servers</p><h1>Servers</h1><p>Every Minecraft world Blockstead looks after on this computer. Open one to reach its console, players, schedule, and settings.</p></div>
    </section>
    {notice && <div className="error page-notice" role="alert">{notice}</div>}
    {list.length > 0 && <div className="server-grid">{list.map((profile, index) => <ServerCard key={profile.id} scope={scopeFor(profile, snapshot, list)} allowlist={rosters[index]?.data?.allowlist.readable ? rosters[index].data.allowlist.players.length : null} schedule={schedules.data?.find(entry => entry.profile_id === profile.id)} onAction={(endpoint, body) => action.mutate({ endpoint, body })} />)}</div>}
    {list.length === 0 && <FirstServerChooser value={firstServerPath} onChange={setFirstServerPath} />}
    {(list.length > 0 || firstServerPath === "create") && <ProvisionPanel stopped={hostFree} onCreated={id => { void navigate(`/servers/${id}/overview`); }} />}
    {(list.length > 0 || firstServerPath === "import") && <section className="card" id="import-server">
      <p className="eyebrow">{list.length ? "Add a server" : "First safe workflow"}</p>
      <h2>Import a server folder</h2>
      <p>Choose your Minecraft server folder — on your Desktop, in Downloads, or anywhere else on this computer. Blockstead copies it into its managed home and never changes the original, so you can delete the original once the imported server runs.</p>
      <form className="inline-form" onSubmit={event => { void uploadFolder(event); }}>
        <label>Profile name<input value={importName} onChange={event => setImportName(event.target.value)} required maxLength={80} /></label>
        <label>Server folder<input type="file" multiple onChange={event => setUploadFiles(Array.from(event.target.files ?? []))} {...folderInputProps} /></label>
        <Button disabled={!uploadFiles.length || uploadProgress != null}>{uploadProgress != null ? `Copying… ${Math.round(uploadProgress * 100)}%` : "Copy folder in"}</Button>
      </form>
      {uploadFiles.length > 0 && uploadProgress == null && <p className="muted-note">Ready to copy “{uploadFiles[0].webkitRelativePath.split("/")[0] || importName}”: {uploadFiles.length.toLocaleString()} file{uploadFiles.length === 1 ? "" : "s"}, {formatBytes(uploadFiles.reduce((sum, file) => sum + file.size, 0))}.</p>}
      {uploadProgress != null && <progress className="upload-progress" value={Math.round(uploadProgress * 100)} max={100} />}
      <details className="import-advanced">
        <summary>The folder is already inside /srv/minecraft</summary>
        <p>Enter its full path. This scan is read-only: the folder is recorded where it is, without copying or changing anything.</p>
        <form className="inline-form" onSubmit={event => { void doScan(event); }}><label>Full path<input value={path} onChange={event => setPath(event.target.value)} placeholder="/srv/minecraft/my-server" required /></label><Button className="button--secondary">Scan folder</Button></form>
        {scan && <div className="scan-plan"><h3>Import plan</h3><p>Detected: {scan.distribution} {scan.minecraft_version}</p><ul>{scan.plan.map(item => <li key={item}>{item}</li>)}</ul><Button onClick={() => void importProfile()}>Confirm profile record</Button></div>}
      </details>
    </section>}
    {(list.length > 0 || firstServerPath === "modpack") && <ModpacksPanel stopped={hostFree} onCreated={id => { void navigate(`/servers/${id}/overview`); }} />}
  </>;
}
