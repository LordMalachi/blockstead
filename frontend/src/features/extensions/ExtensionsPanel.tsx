import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type CatalogSearch,
  type CatalogVersion,
  type ExtensionEntry,
  type ExtensionUpdate,
  type ExtensionUpdates,
  type ExtensionsView,
  type SharedMapView,
} from "../../api/client";
import { Button } from "../../components/Button";
import { NavIcon } from "../../components/NavIcon";
import { Tooltip } from "../../components/Tooltip";
import { formatBytes } from "../../lib/format";
import { ModConfigEditor } from "./ModConfigEditor";
import { SharedMapCard, SHARED_MAP_PROJECT_ID } from "./SharedMapCard";

const SORT_OPTIONS = [
  ["relevance", "Relevance"],
  ["downloads", "Most downloaded"],
  ["follows", "Most followed"],
  ["newest", "Newest"],
  ["updated", "Recently updated"],
] as const;
const MAX_CATALOG_OFFSET = 1000;

export type CatalogSource = "modrinth" | "hangar" | "curseforge";

const SOURCE_LABELS: Record<CatalogSource, string> = {
  modrinth: "Modrinth",
  hangar: "Hangar (PaperMC)",
  curseforge: "CurseForge",
};

interface ActionRequest {
  endpoint: string;
  init: RequestInit;
  success: string;
  afterSuccess?: () => void;
}

function VersionChooser({
  profileId,
  projectId,
  source,
  locked,
  install,
}: {
  profileId: string;
  projectId: string;
  source: CatalogSource;
  locked: boolean;
  install: (versionId: string) => void;
}) {
  const versions = useQuery({
    queryKey: ["extension-versions", profileId, source, projectId],
    queryFn: () => api<{ versions: CatalogVersion[] }>(
      `/profiles/${profileId}/catalog/versions?source=${source}&project_id=${encodeURIComponent(projectId)}`,
    ),
  });

  return <div className="version-drawer">
    <div className="version-drawer__heading">
      <strong>Choose a release</strong>
      <small>Only releases listed for this Minecraft version and loader are shown.</small>
    </div>
    <ul className="version-list">
      {versions.data?.versions.map(version => <li key={version.version_id}>
        <div>
          <strong>{version.version_number ?? version.version_id}</strong>
          <small>{[
            version.version_type,
            version.date_published?.slice(0, 10),
            version.game_versions.length ? `MC ${version.game_versions.join(", ")}` : null,
            version.required_plugins?.length ? `needs ${version.required_plugins.join(", ")}` : null,
          ].filter(Boolean).join(" · ")}</small>
        </div>
        {version.external_url
          ? <a className="button button--quiet button--small" href={version.external_url} target="_blank" rel="noreferrer">Get in browser</a>
          : <Button className="button--secondary button--small" aria-label={`Install version ${version.version_number ?? version.version_id}`} disabled={locked} onClick={() => install(version.version_id)}>Install this version</Button>}
      </li>)}
      {versions.isFetching && <li className="empty-note">Loading versions…</li>}
      {versions.data && !versions.data.versions.length && <li className="empty-note">No releases are listed for this Minecraft version and loader.</li>}
      {versions.error && <li className="empty-note">{versions.error.message}</li>}
    </ul>
  </div>;
}

function ExtensionRow({
  entry,
  disabled,
  locked,
  act,
  update,
}: {
  entry: ExtensionEntry;
  disabled: boolean;
  locked: boolean;
  act: (kind: "toggle" | "remove" | "update", entry: ExtensionEntry, disabled: boolean) => void;
  update?: ExtensionUpdate;
}) {
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const confirmRemove = useRef<HTMLButtonElement>(null);
  const removeTrigger = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  const name = entry.display_name ?? entry.file_name;

  useEffect(() => {
    if (confirmingRemove) {
      returnFocus.current = true;
      confirmRemove.current?.focus();
    } else if (returnFocus.current) {
      returnFocus.current = false;
      removeTrigger.current?.focus();
    }
  }, [confirmingRemove]);

  return <li className={`extension-row${disabled ? " extension-row--disabled" : ""}`}>
    <div className="extension-row__marker" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</div>
    <div className="extension-row__details">
      <div className="extension-row__title">
        <strong>{name}</strong>
        {update && <span className="extension-tag extension-tag--update">Update ready</span>}
        {disabled && <span className="extension-tag">Off</span>}
      </div>
      <span>{entry.version ? `v${entry.version} · ` : ""}{formatBytes(entry.size_bytes)} · {entry.kind.replace("-", " ")}</span>
      <small>{entry.file_name}</small>
      {(entry.minecraft_constraint || entry.loaders.length > 0) && <small className="extension-row__compatibility">
        {[entry.minecraft_constraint ? `Minecraft ${entry.minecraft_constraint}` : null, ...entry.loaders].filter(Boolean).join(" · ")}
      </small>}
    </div>
    {confirmingRemove ? <div className="extension-row__confirm" role="group" aria-label={`Remove ${name}`}>
      <span>Remove {name} from this server?</span>
      <div className="row-actions">
        <Button ref={confirmRemove} className="button--danger button--small" aria-label={`Permanently remove ${name}`} disabled={locked} onClick={() => act("remove", entry, disabled)}>Remove file</Button>
        <Button className="button--quiet button--small" aria-label={`Cancel removing ${name}`} onClick={() => setConfirmingRemove(false)}>Cancel</Button>
      </div>
    </div> : <div className="row-actions extension-row__actions">
      {update && <Button className="button--small" aria-label={`Update ${name} to ${update.new_version_number ?? "latest"}`} disabled={locked} onClick={() => act("update", entry, disabled)}>Update to {update.new_version_number ?? "latest"}</Button>}
      <Button className="button--secondary button--small" aria-label={`${disabled ? "Enable" : "Disable"} ${name}`} disabled={locked} onClick={() => act("toggle", entry, disabled)}>{disabled ? "Enable" : "Disable"}</Button>
      <Button ref={removeTrigger} className="button--quiet button--small" aria-label={`Remove ${name}`} disabled={locked} onClick={() => setConfirmingRemove(true)}>Remove</Button>
    </div>}
  </li>;
}

function ExtensionGuide({ close }: { close: () => void }) {
  return <aside className="workspace-guide" id="extension-guide" aria-labelledby="extension-guide-title">
    <div className="workspace-guide__heading">
      <div>
        <p className="eyebrow">Quick field guide</p>
        <h3 id="extension-guide-title">Change mods and plugins safely</h3>
      </div>
      <Button className="button--quiet button--small" onClick={close}>Close guide</Button>
    </div>
    <ol className="workspace-guide__steps">
      <li><span>1</span><div><strong>Browse while you play</strong><small>Search and compare projects at any time. Results are filtered using this server’s Minecraft version and loader.</small></div></li>
      <li><span>2</span><div><strong>Stop before changing files</strong><small>Installs, updates, uploads, removals, enable/disable actions, and configuration saves wait until Minecraft is safely stopped.</small></div></li>
      <li><span>3</span><div><strong>Review the release</strong><small>Install uses a checksum-verified release that declares support for this setup. Open Versions when you need a specific build.</small></div></li>
      <li><span>4</span><div><strong>Restart and check the console</strong><small>Most changes take effect on the next start. Review the first startup log for dependency or configuration messages.</small></div></li>
    </ol>
    <p className="workspace-guide__note"><strong>Good to know:</strong> Disable keeps a jar nearby for an easy return. Remove deletes that jar from the server, so Blockstead asks again first.</p>
  </aside>;
}

export function ExtensionsPanel({ profileId, stopped }: { profileId: string; stopped: boolean }) {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"success" | "error">("success");
  const [chosenCategories, setChosenCategories] = useState<string[]>([]);
  const [sort, setSort] = useState<string>("relevance");
  const [offset, setOffset] = useState(0);
  const [source, setSource] = useState<CatalogSource>("modrinth");
  const [versionsFor, setVersionsFor] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const guideTrigger = useRef<HTMLButtonElement>(null);

  const inventory = useQuery({
    queryKey: ["extensions", profileId],
    queryFn: () => api<ExtensionsView>(`/profiles/${profileId}/extensions`),
  });
  const sharedMap = useQuery({
    queryKey: ["shared-map", profileId],
    queryFn: () => api<SharedMapView>(`/profiles/${profileId}/shared-map`),
  });
  const curseforge = useQuery({
    queryKey: ["curseforge-settings"],
    queryFn: () => api<{ configured: boolean }>("/settings/curseforge"),
    enabled: source === "curseforge",
  });
  const catalogReady = source !== "curseforge" || curseforge.data?.configured === true;
  const categories = useQuery({
    queryKey: ["extension-categories", profileId, source],
    queryFn: () => api<{ categories: string[] }>(`/profiles/${profileId}/catalog/categories?source=${source}`),
    enabled: inventory.data?.directory != null && catalogReady,
    staleTime: Infinity,
  });
  const results = useQuery({
    queryKey: ["extension-search", profileId, source, searched, chosenCategories, sort, offset],
    queryFn: () => api<CatalogSearch>(
      `/profiles/${profileId}/catalog/search?source=${source}&query=${encodeURIComponent(searched)}&categories=${encodeURIComponent(chosenCategories.join(","))}&sort=${sort}&offset=${offset}`,
    ),
    enabled: Boolean(searched) && catalogReady,
  });
  const updates = useQuery({
    queryKey: ["extension-updates", profileId],
    queryFn: () => api<ExtensionUpdates>(`/profiles/${profileId}/extensions/updates`),
    enabled: false,
  });
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["extensions", profileId] });
    if (updates.data) void updates.refetch();
  };
  const clearNotice = () => setNotice("");
  const showNotice = (tone: "success" | "error", message: string) => {
    setNoticeTone(tone);
    setNotice(message);
  };

  const keyAction = useMutation({
    mutationFn: async ({ endpoint, init }: ActionRequest) => api<unknown>(endpoint, init),
    onSuccess: (_result, request) => {
      showNotice("success", request.success);
      const configured = request.init.method !== "DELETE";
      client.setQueryData(["curseforge-settings"], { configured });
      if (configured) {
        void client.invalidateQueries({ queryKey: ["extension-categories", profileId, "curseforge"] });
        void client.invalidateQueries({ queryKey: ["extension-search", profileId, "curseforge"] });
      } else {
        client.removeQueries({ queryKey: ["extension-categories", profileId, "curseforge"] });
        client.removeQueries({ queryKey: ["extension-search", profileId, "curseforge"] });
      }
    },
    onError: error => showNotice("error", error.message),
  });
  const action = useMutation({
    mutationFn: async ({ endpoint, init }: ActionRequest) => api<unknown>(endpoint, init),
    onSuccess: (_result, request) => {
      showNotice("success", request.success);
      request.afterSuccess?.();
      refresh();
    },
    onError: error => showNotice("error", error.message),
  });

  function manage(kind: "toggle" | "remove" | "update", entry: ExtensionEntry, disabled: boolean) {
    clearNotice();
    const name = entry.display_name ?? entry.file_name;
    if (kind === "toggle") action.mutate({
      endpoint: `/profiles/${profileId}/extensions/toggle`,
      init: { method: "POST", body: JSON.stringify({ file_name: entry.file_name, enabled: disabled }) },
      success: `${name} ${disabled ? "enabled" : "disabled"}. Restart the server for the new loadout to take effect.`,
    });
    else if (kind === "update") action.mutate({
      endpoint: `/profiles/${profileId}/extensions/update`,
      init: { method: "POST", body: JSON.stringify({ file_name: entry.file_name }) },
      success: `${name} updated. Restart the server to load the new release.`,
    });
    else action.mutate({
      endpoint: `/profiles/${profileId}/extensions/${encodeURIComponent(entry.file_name)}?disabled=${disabled}`,
      init: { method: "DELETE" },
      success: `${name} removed from this server.`,
    });
  }

  function bulk(enabled: boolean) {
    clearNotice();
    action.mutate({
      endpoint: `/profiles/${profileId}/extensions/toggle-all`,
      init: { method: "POST", body: JSON.stringify({ enabled }) },
      success: enabled
        ? "Your full loadout is enabled again. Restart the server to bring it back."
        : "Your loadout is safely switched off. Restart the server for a plain Minecraft session.",
    });
  }

  function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim() || !catalogReady) return;
    setOffset(0);
    setVersionsFor(null);
    setSearched(query.trim());
  }

  function toggleCategory(name: string) {
    const limit = source === "curseforge" ? 1 : 5;
    setOffset(0);
    setChosenCategories(current => current.includes(name)
      ? current.filter(item => item !== name)
      : current.length < limit ? [...current, name] : current);
  }

  function switchSource(next: CatalogSource) {
    setSource(next);
    setChosenCategories([]);
    setOffset(0);
    setVersionsFor(null);
  }

  function install(projectId: string, versionId?: string) {
    clearNotice();
    action.mutate({
      endpoint: `/profiles/${profileId}/extensions/install`,
      init: { method: "POST", body: JSON.stringify({ project_id: projectId, source, ...(versionId ? { version_id: versionId } : {}) }) },
      success: "Extension installed and verified. Restart the server to load it.",
    });
  }

  function saveCurseForgeKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = new FormData(form).get("api_key");
    if (typeof value !== "string" || !value.trim()) return;
    clearNotice();
    keyAction.mutate({ endpoint: "/settings/curseforge", init: { method: "PUT", body: JSON.stringify({ api_key: value.trim() }) }, success: "CurseForge key saved. You can search that catalog now." });
  }

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || !file.name) return;
    const body = new FormData();
    body.set("file", file);
    clearNotice();
    action.mutate({
      endpoint: `/profiles/${profileId}/extensions/upload`,
      init: { method: "POST", body },
      success: `${file.name} uploaded. Restart the server to load it.`,
      afterSuccess: () => form.reset(),
    });
  }

  function closeGuide() {
    setGuideOpen(false);
    requestAnimationFrame(() => guideTrigger.current?.focus());
  }

  const view = inventory.data;
  const unsupported = view != null && view.directory == null;
  const activeCount = view?.entries.length ?? 0;
  const disabledCount = view?.disabled_entries.length ?? 0;
  const categoryLimit = source === "curseforge" ? 1 : 5;
  const availableSources = (Object.keys(SOURCE_LABELS) as CatalogSource[])
    .filter(key => key !== "hangar" || view?.directory === "plugins");

  return <section className="card extensions-workspace" id="extensions">
    <header className="workspace-hero workspace-hero--extensions">
      <div className="workspace-hero__copy">
        <p className="eyebrow">Mods and plugins</p>
        <div className="workspace-hero__title">
          <span className="workspace-hero__icon"><NavIcon name="blocks" /></span>
          <h2>Extension Workshop</h2>
        </div>
        <p>Build a server loadout, filter releases for this Minecraft setup, and keep every file change clear and deliberate.</p>
        <div className="workspace-hero__actions">
          <Button ref={guideTrigger} className="button--light button--small" aria-expanded={guideOpen} aria-controls="extension-guide" onClick={() => guideOpen ? closeGuide() : setGuideOpen(true)}>
            {guideOpen ? "Hide extension guide" : "Open extension guide"}
          </Button>
          {view && !unsupported && <span className={`workspace-state${stopped ? " workspace-state--ready" : " workspace-state--locked"}`}>
            <i aria-hidden="true" />{stopped ? "Ready for file changes" : "Browsing open · changes locked"}
          </span>}
        </div>
      </div>
      <div className="workspace-stats" aria-label="Extension summary">
        <article><span>Active</span><strong>{view ? activeCount : "—"}</strong><small>in this loadout</small></article>
        <article><span>Disabled</span><strong>{view ? disabledCount : "—"}</strong><small>kept for later</small></article>
        <article><span>Workshop</span><strong>{!view ? "Loading" : unsupported ? "Unavailable" : stopped ? "Open" : "Browse"}</strong><small>{!view ? "reading this profile" : unsupported ? "vanilla profile" : stopped ? "server stopped" : "install after stop"}</small></article>
      </div>
    </header>

    {guideOpen && <ExtensionGuide close={closeGuide} />}

    {inventory.error && <div className="query-error"><p className="error" role="alert">{inventory.error.message}</p><Button className="button--secondary button--small" onClick={() => void inventory.refetch()}>Try loading extensions again</Button></div>}

    {!view && inventory.isLoading ? <div className="workspace-loading" role="status"><span aria-hidden="true" /><p>Reading this server’s extension loadout…</p></div> : unsupported ? <div className="workspace-empty workspace-empty--blocks">
      <span className="workspace-empty__icon"><NavIcon name="blocks" /></span>
      <div><p className="eyebrow">Vanilla profile</p><h3>This server has no extension loader</h3><p>Vanilla does not load mod jars. Create a Fabric, Forge, Quilt, or NeoForge profile for mods, or a Paper profile for plugins.</p></div>
    </div> : view ? <>
      <nav className="workspace-jump" aria-label="Extension workspace sections">
        <a href="#extension-loadout"><span>01</span><strong>Manage</strong><small>Active and disabled</small></a>
        <a href="#extension-catalog"><span>02</span><strong>Discover</strong><small>Search listed projects</small></a>
        <a href="#extension-config"><span>03</span><strong>Configure</strong><small>Tune generated files</small></a>
      </nav>

      {!stopped && <div className="workspace-lock-note" role="note">
        <span aria-hidden="true">■</span>
        <div><strong>Your loadout is protected while Minecraft is running.</strong><p>Stop the server before changing extension files.</p><small>You can keep browsing and comparing projects in the meantime.</small></div>
      </div>}

      {view?.warnings.length ? <div className="workspace-warning-stack" aria-label="Extension warnings">
        {view.warnings.map(warning => <div className="warning" key={`${warning.code}-${warning.files.join()}`}>
          <strong>{warning.code.replace("-", " ")}</strong>
          <span>{warning.message}</span>
          <small>{warning.files.join(", ")}</small>
        </div>)}
      </div> : null}

      {view.truncated && <div className="warning"><strong>Large loadout</strong><span>Showing the first 200 extension files. The counts and lists may not include every jar in this server.</span></div>}

      <section className="workspace-section extension-loadout" id="extension-loadout" aria-labelledby="loadout-heading">
        <div className="workspace-section__heading">
          <div>
            <p className="eyebrow">Your loadout</p>
            <div className="heading-with-help">
              <h3 id="loadout-heading">Installed extensions</h3>
              <Tooltip label="Why extension changes require a stopped server">Minecraft loads jars at startup and may keep their files open while it runs. Waiting for a full stop prevents partial updates and unclear dependency states.</Tooltip>
            </div>
            <p>See what will load on the next start, park files without deleting them, and check recognized projects for updates.</p>
          </div>
          <Button className="button--secondary button--small" disabled={!view?.entries.length || updates.isFetching} onClick={() => { clearNotice(); void updates.refetch(); }}>
            {updates.isFetching ? "Checking…" : "Check for updates"}
          </Button>
        </div>

        {view && (activeCount > 0 || disabledCount > 0) && <div className="vanilla-switch">
          <span className="vanilla-switch__icon" aria-hidden="true">▦</span>
          <div>
            <strong>Vanilla switch</strong>
            <span>{activeCount
              ? `Turn all ${activeCount} ${view.directory === "plugins" ? "plugins" : "mods"} off at once to play plain Minecraft. Nothing is deleted, and everything can come back with one click.`
              : "Everything is off — the server plays like plain Minecraft. Bring it all back whenever you like."}</span>
          </div>
          <div className="row-actions">
            {activeCount > 0 && <Button className="button--secondary button--small" disabled={!stopped || action.isPending} onClick={() => bulk(false)}>Disable all</Button>}
            {disabledCount > 0 && <Button className="button--secondary button--small" disabled={!stopped || action.isPending} onClick={() => bulk(true)}>Enable all</Button>}
          </div>
        </div>}

        {updates.data && !updates.isFetching && <p className="update-summary" role="status">
          {updates.data.updates.length ? `${updates.data.updates.length} update${updates.data.updates.length === 1 ? "" : "s"} available.` : "Everything Modrinth recognizes is up to date."}
          {updates.data.unknown.length ? ` ${updates.data.unknown.length} file${updates.data.unknown.length === 1 ? " was" : "s were"} not matched to Modrinth.` : ""}
        </p>}
        {updates.error && <div className="query-error"><p className="error" role="alert">Update check failed: {updates.error.message}</p><Button className="button--secondary button--small" onClick={() => void updates.refetch()}>Check again</Button></div>}

        <div className="extension-columns">
          <div className="extension-list-panel">
            <div className="list-heading"><h4>Active</h4><span>{activeCount}</span></div>
            <ul className="extension-list">
              {view?.entries.map(entry => <ExtensionRow
                key={entry.file_name}
                entry={entry}
                disabled={false}
                locked={!stopped || action.isPending}
                act={manage}
                update={updates.data?.updates.find(item => item.file_name === entry.file_name)}
              />)}
              {view && !activeCount && <li className="empty-note">No active files in {view.directory}/.</li>}
            </ul>
          </div>
          <div className="extension-list-panel extension-list-panel--disabled">
            <div className="list-heading"><h4>Disabled</h4><span>{disabledCount}</span></div>
            <ul className="extension-list">
              {view?.disabled_entries.map(entry => <ExtensionRow key={entry.file_name} entry={entry} disabled locked={!stopped || action.isPending} act={manage} />)}
              {view && !disabledCount && <li className="empty-note">Nothing is disabled.</li>}
            </ul>
          </div>
        </div>
      </section>

      {view && <SharedMapCard
        entries={view.entries}
        disabledEntries={view.disabled_entries}
        map={sharedMap.data}
        stopped={stopped}
        busy={action.isPending}
        install={() => action.mutate({
          endpoint: `/profiles/${profileId}/extensions/install`,
          init: { method: "POST", body: JSON.stringify({ project_id: SHARED_MAP_PROJECT_ID }) },
          success: "squaremap installed and verified. Start the server to finish its setup.",
        })}
      />}

      <section className="workspace-section catalog-workbench" id="extension-catalog" aria-labelledby="catalog-heading">
        <div className="workspace-section__heading">
          <div>
            <p className="eyebrow">Discover</p>
            <div className="heading-with-help">
              <h3 id="catalog-heading">Find projects for this server</h3>
              <Tooltip label="How project filtering works">Results are filtered by this profile’s Minecraft version and loader. Installs verify published checksums and include required dependencies, but Blockstead cannot guarantee that add-ons work together.</Tooltip>
            </div>
            <p>Browse freely while the server runs; installation buttons unlock after a safe stop.</p>
          </div>
          {results.data && <span className="section-count">{results.data.total?.toLocaleString() ?? results.data.projects.length} matches</span>}
        </div>

        <form className="catalog-search" role="search" onSubmit={search}>
          <label>
            <span>Search projects listed for this server</span>
            <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Try Lithium, LuckPerms, voice chat…" />
          </label>
          <Button disabled={!query.trim() || !catalogReady || results.isFetching}>{results.isFetching ? "Searching…" : source === "curseforge" && !catalogReady ? "Add key to search" : "Search"}</Button>
        </form>

        <div className="catalog-browser">
          <aside className="catalog-sidebar" aria-label="Catalog filters">
            <label>Catalog
              <select value={source} onChange={event => switchSource(event.target.value as CatalogSource)}>
                {availableSources.map(key => <option key={key} value={key}>{SOURCE_LABELS[key]}</option>)}
              </select>
            </label>
            <label>Sort by
              <select value={sort} onChange={event => { setSort(event.target.value); setOffset(0); }}>
                {SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            {Boolean(categories.data?.categories?.length) && <div className="catalog-category-filter">
              <div><strong>Categories</strong><small>{chosenCategories.length}/{categoryLimit} selected</small></div>
              <div className="category-chips" role="group" aria-label="Category filters">
                {categories.data?.categories.map(name => <button
                  key={name}
                  type="button"
                  className={chosenCategories.includes(name) ? "chip chip--on" : "chip"}
                  aria-pressed={chosenCategories.includes(name)}
                  disabled={!chosenCategories.includes(name) && chosenCategories.length >= categoryLimit}
                  onClick={() => toggleCategory(name)}
                >{name.replace(/[_-]/g, " ")}</button>)}
              </div>
              {chosenCategories.length > 0 && <Button className="button--quiet button--small" onClick={() => { setChosenCategories([]); setOffset(0); }}>Clear filters</Button>}
            </div>}
            {categories.error && <p className="catalog-filter-error" role="alert">Categories unavailable: {categories.error.message}</p>}
            <p className="catalog-safety-note"><span aria-hidden="true">◆</span> Downloads are checksum-verified before installation.</p>
          </aside>

          <div className="catalog-content">
            {source === "curseforge" && curseforge.data && !curseforge.data.configured && <form className="curseforge-key-form" onSubmit={saveCurseForgeKey}>
              <div><strong>Connect your CurseForge key</strong><p>Searching CurseForge needs your own free API key. Blockstead stores it on this computer only and never shows it again.</p></div>
              <label>CurseForge API key<input name="api_key" type="password" required minLength={8} placeholder="Paste your key" /></label>
              <Button disabled={keyAction.isPending}>Save key</Button>
            </form>}
            {source === "curseforge" && curseforge.data?.configured && <div className="catalog-key-status"><span>CurseForge is connected on this computer.</span><Button className="button--quiet button--small" disabled={keyAction.isPending} onClick={() => { clearNotice(); keyAction.mutate({ endpoint: "/settings/curseforge", init: { method: "DELETE" }, success: "CurseForge key removed from this computer." }); }}>Remove key</Button></div>}
            {source === "curseforge" && curseforge.error && <div className="query-error"><p className="error" role="alert">CurseForge settings could not be loaded: {curseforge.error.message}</p><Button className="button--secondary button--small" onClick={() => void curseforge.refetch()}>Try again</Button></div>}

            {!searched && <div className="catalog-empty">
              <span className="catalog-empty__blocks" aria-hidden="true"><i /><i /><i /></span>
              <h4>What do you want to add?</h4>
              <p>Search by project name or purpose. Good starting ideas are performance, permissions, maps, or voice chat.</p>
            </div>}
            {results.isFetching && <p className="empty-note" role="status">Searching {SOURCE_LABELS[source]}…</p>}
            {results.error && <p className="error" role="alert">{results.error.message}</p>}
            <div className="catalog-results">
              {results.data?.projects.map(project => {
                const title = project.title ?? project.slug ?? project.project_id;
                return <article key={project.project_id}>
                  <div className="catalog-project__marker" aria-hidden="true">{title.slice(0, 1).toUpperCase()}</div>
                  <div className="catalog-project__copy">
                    <div className="catalog-project__title"><strong>{title}</strong><span>{SOURCE_LABELS[source]}</span></div>
                    <p>{project.description || "No project description was provided."}</p>
                    <small>{project.author ? `by ${project.author} · ` : ""}{project.downloads?.toLocaleString() ?? "—"} downloads{project.page_url ? <> · <a aria-label={`Open ${title} project page`} href={project.page_url} target="_blank" rel="noreferrer">project page</a></> : null}</small>
                    {versionsFor === project.project_id && <VersionChooser profileId={profileId} projectId={project.project_id} source={source} locked={!stopped || action.isPending} install={versionId => install(project.project_id, versionId)} />}
                  </div>
                  <div className="row-actions catalog-project__actions">
                    {project.installable === false
                      ? project.page_url
                        ? <a className="button button--secondary button--small" href={project.page_url} target="_blank" rel="noreferrer">Get in browser</a>
                        : <span className="catalog-project__unavailable">Manual download only</span>
                      : <Button className="button--secondary button--small" aria-label={`Install ${title}`} disabled={!stopped || action.isPending} onClick={() => install(project.project_id)}>Install</Button>}
                    <Button className="button--quiet button--small" aria-label={`${versionsFor === project.project_id ? "Hide" : "Show"} versions for ${title}`} aria-expanded={versionsFor === project.project_id} onClick={() => setVersionsFor(versionsFor === project.project_id ? null : project.project_id)}>{versionsFor === project.project_id ? "Hide versions" : "Versions"}</Button>
                  </div>
                </article>;
              })}
              {results.data && !results.data.projects.length && <div className="catalog-empty catalog-empty--small"><h4>No matches this time</h4><p>Try a shorter search or clear one of the category filters.</p></div>}
            </div>
            {results.data && (results.data.total ?? 0) > (results.data.limit ?? 20) && <div className="pager">
              <Button className="button--quiet button--small" disabled={offset === 0 || results.isFetching} onClick={() => { setVersionsFor(null); setOffset(Math.max(0, offset - (results.data?.limit ?? 20))); }}>Previous</Button>
              <span>{offset + 1}–{Math.min(offset + (results.data.limit ?? 20), results.data.total ?? 0)} of {results.data.total?.toLocaleString()}</span>
              <Button className="button--quiet button--small" disabled={offset >= MAX_CATALOG_OFFSET || offset + (results.data.limit ?? 20) >= (results.data.total ?? 0) || results.isFetching} onClick={() => { setVersionsFor(null); setOffset(Math.min(MAX_CATALOG_OFFSET, offset + (results.data?.limit ?? 20))); }}>Next</Button>
            </div>}
          </div>
        </div>
      </section>

      <section className="manual-install" aria-labelledby="manual-install-heading">
        <div>
          <p className="eyebrow">Bring your own file</p>
          <h3 id="manual-install-heading">Upload a jar</h3>
          <p>Only upload a jar from a source you trust when it is not in a connected catalog. Blockstead records the file, but cannot verify its origin or guarantee that it works with your loadout.</p>
        </div>
        <form className="upload-form" onSubmit={upload}>
          <label>Local .jar file<input name="file" type="file" accept=".jar,application/java-archive" required /></label>
          <Button disabled={!stopped || action.isPending}>Upload</Button>
        </form>
      </section>

      <section className="workspace-section extension-configuration" id="extension-config" aria-label="Extension configuration">
        <p className="eyebrow">Tune the details</p>
        <ModConfigEditor profileId={profileId} stopped={stopped} />
      </section>
    </> : null}

    {notice && <div className={`workspace-toast ${noticeTone}`} role={noticeTone === "error" ? "alert" : "status"}>
      <span>{notice}</span>
      <button type="button" aria-label="Dismiss message" onClick={clearNotice}>×</button>
    </div>}
  </section>;
}
