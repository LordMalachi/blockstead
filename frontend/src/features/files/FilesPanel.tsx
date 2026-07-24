import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  apiBlob,
  apiUpload,
  type ArchiveExtractResult,
  type FileCategory,
  type FileContent,
  type FileDeleteResult,
  type FileEditPreview,
  type FileEditResult,
  type FileListing,
  type FileNode,
  type FileRenameResult,
  type FileUploadResult,
} from "../../api/client";
import { Button } from "../../components/Button";
import { NavIcon } from "../../components/NavIcon";
import { formatBytes } from "../../lib/format";

const CATEGORIES: { value: FileCategory; label: string; hint: string }[] = [
  { value: "config", label: "Config", hint: "server.properties, eula.txt, and loader configuration" },
  { value: "logs", label: "Logs", hint: "Recent server and crash logs, read-only" },
  { value: "extensions", label: "Extensions", hint: "Installed plugin or mod jars and their data folders" },
  { value: "world", label: "World", hint: "Recognized world folders only" },
  { value: "backups", label: "Backups", hint: "Existing backup archives, download only" },
];

function formatWhen(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function segments(path: string): { name: string; path: string }[] {
  if (!path) return [];
  const parts = path.split("/");
  return parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join("/") }));
}

async function downloadEntry(profileId: string, category: FileCategory, path: string, name: string) {
  const blob = await apiBlob(`/profiles/${profileId}/files/${category}/download?path=${encodeURIComponent(path)}`);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export function FilesPanel({
  profileId,
  distribution,
  stopped,
}: {
  profileId: string;
  distribution: string;
  stopped: boolean;
}) {
  const cache = useQueryClient();
  const uploadInput = useRef<HTMLInputElement>(null);
  const extractInput = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState<FileCategory>("config");
  const [path, setPath] = useState("");
  const [openFile, setOpenFile] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [extractProgress, setExtractProgress] = useState<number | null>(null);

  useEffect(() => { setPath(""); setOpenFile(null); setDraft(null); setNotice(""); }, [category, profileId]);
  useEffect(() => { setOpenFile(null); setDraft(null); }, [path]);

  const listing = useQuery({
    queryKey: ["files", profileId, category, path],
    queryFn: () => api<FileListing>(`/profiles/${profileId}/files/${category}?path=${encodeURIComponent(path)}`),
  });
  const content = useQuery({
    queryKey: ["file-content", profileId, category, openFile],
    queryFn: () => api<FileContent>(`/profiles/${profileId}/files/${category}/content?path=${encodeURIComponent(openFile ?? "")}`),
    enabled: openFile != null,
  });

  const check = useMutation({
    mutationFn: (payload: { path: string; revision: string; content: string }) =>
      api<FileEditPreview>(`/profiles/${profileId}/files/${category}/content/preview`, { method: "POST", body: JSON.stringify(payload) }),
  });
  const save = useMutation({
    mutationFn: (payload: { path: string; revision: string; content: string }) =>
      api<FileEditResult>(`/profiles/${profileId}/files/${category}/content`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: result => {
      setNotice(`Saved. Recovery snapshot ${result.snapshot_name} was created.`);
      setDraft(null);
      check.reset();
      void cache.invalidateQueries({ queryKey: ["files", profileId, category] });
      void cache.invalidateQueries({ queryKey: ["file-content", profileId, category, openFile] });
    },
  });
  const rename = useMutation({
    mutationFn: (payload: { path: string; new_name: string }) =>
      api<FileRenameResult>(`/profiles/${profileId}/files/${category}/rename`, { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => {
      setRenaming(null);
      setNotice("Renamed.");
      void cache.invalidateQueries({ queryKey: ["files", profileId, category] });
    },
  });
  const remove = useMutation({
    mutationFn: (targetPath: string) =>
      api<FileDeleteResult>(`/profiles/${profileId}/files/${category}?path=${encodeURIComponent(targetPath)}`, { method: "DELETE" }),
    onSuccess: (result, targetPath) => {
      setConfirmDelete(null);
      if (openFile === targetPath) setOpenFile(null);
      setNotice(result.snapshot_name
        ? `Deleted. Recovery snapshot ${result.snapshot_name} was created.`
        : `Deleted. The folder was preserved as ${result.preserved_name}.`);
      void cache.invalidateQueries({ queryKey: ["files", profileId, category] });
    },
  });
  const upload = useMutation({
    mutationFn: (files: FileList) => {
      const form = new FormData();
      form.append("path", path);
      for (const file of Array.from(files)) form.append("files", file);
      return apiUpload<FileUploadResult>(`/profiles/${profileId}/files/${category}/upload`, form, (loaded, total) => setUploadProgress(total ? loaded / total : null));
    },
    onSuccess: result => {
      setUploadProgress(null);
      setNotice(`Uploaded ${result.uploaded.length} file${result.uploaded.length === 1 ? "" : "s"}.`);
      if (uploadInput.current) uploadInput.current.value = "";
      void cache.invalidateQueries({ queryKey: ["files", profileId, category] });
    },
    onError: () => setUploadProgress(null),
  });
  const extract = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("path", path);
      form.append("file", file);
      return apiUpload<ArchiveExtractResult>(`/profiles/${profileId}/files/${category}/archive/extract`, form, (loaded, total) => setExtractProgress(total ? loaded / total : null));
    },
    onSuccess: result => {
      setExtractProgress(null);
      if (extractInput.current) extractInput.current.value = "";
      setNotice(`Extracted ${result.promoted.length} item${result.promoted.length === 1 ? "" : "s"}.`
        + (result.preserved.length ? ` ${result.preserved.length} existing item${result.preserved.length === 1 ? "" : "s"} preserved.` : ""));
      void cache.invalidateQueries({ queryKey: ["files", profileId, category] });
    },
    onError: () => setExtractProgress(null),
  });

  function openEntry(entry: FileNode) {
    if (entry.is_dir) { setPath(entry.path); return; }
    if (entry.viewable) { setOpenFile(entry.path); setDraft(null); check.reset(); save.reset(); setNotice(""); }
  }

  const writable = listing.data?.writable ?? false;
  const stopRequired = listing.data?.stopped_required ?? false;
  const locked = stopRequired && !stopped;
  const isTopLevelWorldEntry = (entryPath: string) => category === "world" && path === "" && !entryPath.includes("/");
  const visibleCategories = CATEGORIES.filter(item => item.value !== "extensions" || distribution !== "vanilla");
  const fileValue = content.data;
  const editText = draft ?? fileValue?.content ?? "";
  const checked = check.data && check.variables?.content === editText ? check.data : null;

  return <section className="card files-workspace" id="files">
    <div className="section-heading">
      <div><p className="eyebrow">Safe file workspace</p><h2>Files</h2></div>
    </div>
    <p className="muted-note">Browse only the approved server folders. Uploads, edits, and archive extraction always create a recovery point first.</p>

    <div className="history-filter" role="group" aria-label="File category">
      {visibleCategories.map(item => <button key={item.value} type="button" className={category === item.value ? "active" : ""} aria-pressed={category === item.value} onClick={() => setCategory(item.value)}>{item.label}</button>)}
    </div>
    <p className="muted-note">{CATEGORIES.find(item => item.value === category)?.hint}</p>

    <nav className="file-breadcrumb" aria-label="Folder path">
      <button type="button" aria-label={`${category[0].toUpperCase() + category.slice(1)} root folder`} onClick={() => setPath("")} disabled={!path}>{category[0].toUpperCase() + category.slice(1)}</button>
      {segments(path).map(segment => <span key={segment.path}><span aria-hidden="true">/</span><button type="button" onClick={() => setPath(segment.path)} disabled={segment.path === path}>{segment.name}</button></span>)}
    </nav>

    {locked && <p className="warning">Stop the server before uploading, renaming, deleting, or extracting archives in this category.</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {downloadError && <p className="error" role="alert">{downloadError}</p>}

    {listing.isLoading ? <p className="empty-note">Loading…</p>
      : listing.error ? <div className="query-error"><p className="error" role="alert">{listing.error.message}</p><Button className="button--secondary button--small" onClick={() => void listing.refetch()}>Try again</Button></div>
        : listing.data && listing.data.entries.length === 0 ? <p className="empty-note">Nothing here yet.</p>
          : listing.data && <ul className="file-list">
            {listing.data.entries.map(entry => <li key={entry.path} className="file-row">
              <button type="button" className="file-row__name" disabled={!entry.is_dir && !entry.viewable} onClick={() => openEntry(entry)}>
                <NavIcon name={entry.is_dir ? "folder" : "history"} />
                <span>{entry.name}</span>
              </button>
              <span className="file-row__meta">{entry.is_dir ? "Folder" : formatBytes(entry.size_bytes ?? 0)}</span>
              <span className="file-row__meta">{formatWhen(entry.modified_at)}</span>
              <div className="file-row__actions">
                {!entry.is_dir && <Button className="button--quiet button--small" onClick={() => { setDownloadError(""); void downloadEntry(profileId, category, entry.path, entry.name).catch(error => setDownloadError(error instanceof Error ? error.message : "The download failed.")); }}>Download</Button>}
                {writable && !locked && !isTopLevelWorldEntry(entry.path) && (renaming === entry.path
                  ? <form className="file-row__rename" onSubmit={event => { event.preventDefault(); if (renameValue.trim()) rename.mutate({ path: entry.path, new_name: renameValue.trim() }); }}>
                      <input aria-label={`New name for ${entry.name}`} value={renameValue} onChange={event => setRenameValue(event.target.value)} autoFocus />
                      <Button className="button--secondary button--small" disabled={rename.isPending}>Save</Button>
                      <Button type="button" className="button--quiet button--small" onClick={() => setRenaming(null)}>Cancel</Button>
                    </form>
                  : <Button className="button--quiet button--small" onClick={() => { setRenaming(entry.path); setRenameValue(entry.name); }}>Rename</Button>)}
                {writable && !locked && !isTopLevelWorldEntry(entry.path) && (confirmDelete === entry.path
                  ? <Button className="button--danger button--small" disabled={remove.isPending} onClick={() => remove.mutate(entry.path)}>{remove.isPending ? "Deleting…" : "Confirm delete"}</Button>
                  : <Button className="button--quiet button--small" onClick={() => setConfirmDelete(entry.path)}>Delete</Button>)}
              </div>
            </li>)}
          </ul>}
    {rename.error && <p className="error" role="alert">{rename.error.message}</p>}
    {remove.error && <p className="error" role="alert">{remove.error.message}</p>}

    {openFile && <section className="file-editor" aria-label={`View ${openFile}`}>
      <div className="section-heading"><div><p className="eyebrow">{openFile}</p><h3>{fileValue?.editable ? "Edit file" : "View file"}</h3></div><Button className="button--quiet button--small" onClick={() => setOpenFile(null)}>Close</Button></div>
      {content.isLoading ? <p className="empty-note">Loading file…</p>
        : content.error ? <p className="error" role="alert">{content.error.message}</p>
          : fileValue && (fileValue.editable
            ? <>
                <textarea className="raw-editor__text" aria-label={`Content of ${openFile}`} rows={16} spellCheck={false} value={editText} onChange={event => { setDraft(event.target.value); save.reset(); }} />
                <div className="settings-actions">
                  <Button className="button--secondary" disabled={check.isPending} onClick={() => check.mutate({ path: openFile, revision: fileValue.revision, content: editText })}>{check.isPending ? "Checking…" : "Check changes"}</Button>
                  <Button disabled={!checked?.valid || checked.no_changes || save.isPending} onClick={() => save.mutate({ path: openFile, revision: fileValue.revision, content: editText })}>{save.isPending ? "Saving safely…" : "Save file"}</Button>
                </div>
                {checked && checked.problems.length > 0 && <ul className="raw-problems" aria-label="Validation problems">{checked.problems.map(problem => <li key={problem} className="error">{problem}</li>)}</ul>}
                {checked?.valid && (checked.no_changes ? <p className="muted-note">Nothing has changed yet.</p> : <p className="success" role="status">Ready to save.</p>)}
                {save.error && <p className="error" role="alert">{save.error.message}</p>}
              </>
            : <pre className="file-editor__readonly">{fileValue.content}</pre>)}
    </section>}

    {writable && <section className="file-upload" aria-label="Upload files">
      <div className="section-heading"><div><p className="eyebrow">Add files</p><h3>Upload into this folder</h3></div></div>
      <p className="muted-note">A file with an existing name is refused; rename or delete it first.</p>
      <div className="inline-form">
        <label>Choose files<input ref={uploadInput} type="file" multiple disabled={locked || upload.isPending} onChange={event => { if (event.target.files?.length) upload.mutate(event.target.files); }} /></label>
      </div>
      {uploadProgress != null && <div className="backup-progress" role="status" aria-live="polite"><span className="backup-progress__pulse" aria-hidden="true" /><div><strong>Uploading…</strong><p>{Math.round(uploadProgress * 100)}%</p></div></div>}
      {upload.error && <p className="error" role="alert">{upload.error.message}</p>}
    </section>}

    {writable && <section className="file-upload" aria-label="Extract an archive">
      <div className="section-heading"><div><p className="eyebrow">Bulk add</p><h3>Extract a .zip archive here</h3></div></div>
      <p className="muted-note">New files are added to this folder. Anything with a matching name is preserved beside it rather than overwritten.</p>
      <div className="inline-form">
        <label>Choose a .zip file<input ref={extractInput} type="file" accept=".zip" disabled={locked || extract.isPending} onChange={event => { const file = event.target.files?.[0]; if (file) extract.mutate(file); }} /></label>
      </div>
      {extractProgress != null && <div className="backup-progress" role="status" aria-live="polite"><span className="backup-progress__pulse" aria-hidden="true" /><div><strong>Extracting…</strong><p>{Math.round(extractProgress * 100)}%</p></div></div>}
      {extract.error && <p className="error" role="alert">{extract.error.message}</p>}
    </section>}
  </section>;
}
