import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, apiBlob } from "../../api/client";
import { Button } from "../../components/Button";

const MAX_VISIBLE_LOG_LINES = 50;
const EMPTY_BATCH_IDS: readonly string[] = [];

export interface LoadoutTestQuarantine {
  file_name: string;
  reason: string;
}

export interface LoadoutTestResult {
  run_id: string;
  status: "passed" | "failed";
  summary: string;
  log_tail: string[];
  log_lines_truncated: boolean;
  quarantined: LoadoutTestQuarantine[];
  retry_allowed: boolean;
  warnings?: string[];
}

export interface LoadoutLockfileReviewChange {
  file_name: string;
  action: "install" | "update" | "downgrade" | "keep" | "remove" | "unavailable";
  detail: string;
}

export interface LoadoutLockfileReview {
  review_id: string;
  minecraft_version: string;
  distribution: string;
  loader_version: string | null;
  changes: LoadoutLockfileReviewChange[];
  exclusions: string[];
  manual_requirements: string[];
  warnings: string[];
  blockers: string[];
  expires_in_seconds: number;
}

interface PlayerPackReviewFile {
  file_name: string;
  reason?: string;
}

interface PlayerPackReview {
  review_id: string;
  file_name: string;
  dependencies: Record<string, string>;
  included: PlayerPackReviewFile[];
  manual_requirements: PlayerPackReviewFile[];
  disclosures: Array<PlayerPackReviewFile & { message: string }>;
  excluded: PlayerPackReviewFile[];
}

export interface LoadoutSafetyPanelProps {
  profileId: string;
  stopped: boolean;
  recentlyInstalledBatchIds?: readonly string[];
  playerPackAvailable?: boolean;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

async function download(path: string, fileName: string): Promise<void> {
  const blob = await apiBlob(path);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

export function LoadoutSafetyPanel({
  profileId,
  stopped,
  recentlyInstalledBatchIds = EMPTY_BATCH_IDS,
  playerPackAvailable = true,
}: LoadoutSafetyPanelProps) {
  const lockfileInput = useRef<HTMLInputElement>(null);
  const [testResult, setTestResult] = useState<LoadoutTestResult | null>(null);
  const [lockfileReview, setLockfileReview] = useState<LoadoutLockfileReview | null>(null);
  const [downloadNotice, setDownloadNotice] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [downloadBusy, setDownloadBusy] = useState<"lockfile" | "player-pack" | null>(null);
  const [pendingBatchIds, setPendingBatchIds] = useState<string[]>([...recentlyInstalledBatchIds]);
  const [playerPackReview, setPlayerPackReview] = useState<PlayerPackReview | null>(null);

  useEffect(() => {
    setTestResult(null);
    setLockfileReview(null);
    setDownloadNotice("");
    setDownloadError("");
    setDownloadBusy(null);
    setPlayerPackReview(null);
    setPendingBatchIds([...recentlyInstalledBatchIds]);
    if (lockfileInput.current) lockfileInput.current.value = "";
  }, [profileId, recentlyInstalledBatchIds]);

  const testStart = useMutation({
    mutationFn: (retryOf?: string) => api<LoadoutTestResult>(`/profiles/${profileId}/loadout/test-start`, {
      method: "POST",
      body: JSON.stringify({
        recent_batch_ids: pendingBatchIds,
        retry_of: retryOf ?? null,
      }),
    }),
    onMutate: () => setTestResult(null),
    onSuccess: result => {
      setTestResult(result);
      if (result.status === "passed") {
        setPendingBatchIds([]);
      }
    },
  });

  const reviewLockfile = useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.set("file", file);
      return api<LoadoutLockfileReview>(`/profiles/${profileId}/loadout/lockfile/review`, {
        method: "POST",
        body,
      });
    },
    onMutate: () => setLockfileReview(null),
    onSuccess: setLockfileReview,
  });

  const reviewPlayerPack = useMutation({
    mutationFn: () => api<PlayerPackReview>(
      `/profiles/${profileId}/loadout/player-pack/review`,
    ),
    onMutate: () => {
      setPlayerPackReview(null);
      setDownloadError("");
    },
    onSuccess: setPlayerPackReview,
  });

  async function downloadArtifact(kind: "lockfile" | "player-pack") {
    setDownloadBusy(kind);
    setDownloadNotice("");
    setDownloadError("");
    try {
      const path = kind === "lockfile"
        ? `/profiles/${profileId}/loadout/lockfile`
        : `/profiles/${profileId}/loadout/player-pack?review_id=${playerPackReview?.review_id ?? ""}`;
      const fileName = kind === "lockfile"
        ? `blockstead-loadout-${profileId}.lock.json`
        : `blockstead-player-pack-${profileId}.mrpack`;
      await download(path, fileName);
      setDownloadNotice(kind === "lockfile"
        ? "Loadout lockfile downloaded."
        : "Player pack downloaded. Review the exclusions and manual requirements before sharing it.");
    } catch (error) {
      setDownloadError(errorMessage(error, "The download failed."));
    } finally {
      setDownloadBusy(null);
    }
  }

  const visibleLogs = testResult?.log_tail.slice(-MAX_VISIBLE_LOG_LINES) ?? [];
  const logsWereBounded = (testResult?.log_tail.length ?? 0) > MAX_VISIBLE_LOG_LINES;
  const testDisabled = !stopped || testStart.isPending;

  return <section className="workspace-section loadout-safety" id="loadout-safety" aria-labelledby="loadout-safety-heading">
    <div>
      <p className="eyebrow">Before players return</p>
      <h2 id="loadout-safety-heading">Test and preserve this loadout</h2>
      <p>Check a changed mod or plugin set privately, save an exact version record, or prepare the client files players need.</p>
    </div>

    <article className="extension-update-review" aria-labelledby="safe-test-start-heading">
      <div>
        <h3 id="safe-test-start-heading">Safe test start</h3>
        <p>Blockstead starts the server in a private validation mode. Player connections stay closed while startup logs and newly installed files are checked.</p>
      </div>
      <div className="row-actions">
        <Button disabled={testDisabled} onClick={() => testStart.mutate(undefined)}>
          {testStart.isPending ? "Testing privately…" : "Run safe test start"}
        </Button>
      </div>
      {!stopped && <p className="warning">Stop the server before running a private test start.</p>}
      {testStart.error && <p className="error" role="alert">{testStart.error.message}</p>}
      {testResult && <div className={testResult.status === "passed" ? "success" : "error"} role="status">
        <strong>{testResult.status === "passed" ? "Private test passed" : "Private test failed"}</strong>
        <span>{testResult.summary}</span>
      </div>}
      {testResult && visibleLogs.length > 0 && <details>
        <summary>Startup log summary</summary>
        <pre aria-label="Private test startup logs">{visibleLogs.join("\n")}</pre>
      </details>}
      {testResult && (testResult.log_lines_truncated || logsWereBounded) && <small>Showing only the most recent {visibleLogs.length} log lines.</small>}
      {testResult?.warnings?.map(item => <p className="warning" key={item}>{item}</p>)}
      {testResult && testResult.quarantined.length > 0 && <div>
        <h4>Quarantined from this test</h4>
        <p>These files were disabled without changing the world. Review them before retrying.</p>
        <ul>{testResult.quarantined.map(item => <li key={item.file_name}>
          <strong>{item.file_name}</strong>
          <span>{item.reason}</span>
        </li>)}</ul>
      </div>}
      {testResult?.retry_allowed && <div className="row-actions">
        <Button
          className="button--secondary"
          disabled={testDisabled}
          onClick={() => testStart.mutate(testResult.run_id)}
        >
          Retry without quarantined files
        </Button>
      </div>}
    </article>

    <div className="extension-columns">
      <article className="extension-list-panel">
        <h3>Loadout lockfile</h3>
        <p>Download the exact Minecraft, loader, extension versions, checksums, dependencies, and recorded sources for this server.</p>
        <div className="row-actions">
          <Button
            className="button--secondary"
            disabled={downloadBusy != null}
            onClick={() => void downloadArtifact("lockfile")}
          >
            {downloadBusy === "lockfile" ? "Preparing lockfile…" : "Download lockfile"}
          </Button>
          <Button
            className="button--quiet"
            disabled={reviewLockfile.isPending}
            onClick={() => lockfileInput.current?.click()}
          >
            {reviewLockfile.isPending ? "Reviewing…" : "Review a lockfile"}
          </Button>
          <input
            ref={lockfileInput}
            aria-label="Choose a loadout lockfile"
            type="file"
            accept=".json,application/json"
            hidden
            onChange={event => {
              const file = event.target.files?.[0];
              if (file) reviewLockfile.mutate(file);
              event.target.value = "";
            }}
          />
        </div>
        <small>Import is review-only. Nothing will be installed, removed, or changed from this screen.</small>
        {reviewLockfile.error && <p className="error" role="alert">{reviewLockfile.error.message}</p>}
      </article>

      <article className="extension-list-panel">
        <h3>Player pack</h3>
        <p>{playerPackAvailable
          ? "Export a Modrinth-compatible pack containing the client-required part of this server’s loadout."
          : "Paper plugins stay on the server, so players do not need a client mod pack for this profile."}</p>
        <ul>
          <li>Server-only mods and plugins are excluded.</li>
          <li>Files that cannot be redistributed are listed as manual requirements.</li>
          <li>Players may still need the matching launcher, Minecraft version, and loader.</li>
        </ul>
        <Button
          className="button--secondary"
          disabled={downloadBusy != null || !playerPackAvailable || reviewPlayerPack.isPending}
          onClick={() => reviewPlayerPack.mutate()}
        >
          {reviewPlayerPack.isPending ? "Reviewing player files…" : playerPackReview ? "Refresh player-pack review" : "Review player pack"}
        </Button>
        <Button
          className="button--secondary"
          disabled={downloadBusy != null || !playerPackAvailable || !playerPackReview}
          onClick={() => void downloadArtifact("player-pack")}
        >
          {downloadBusy === "player-pack" ? "Preparing player pack…" : playerPackAvailable ? "Download reviewed player pack" : "Not needed for Paper"}
        </Button>
        {reviewPlayerPack.error && <p className="error" role="alert">{reviewPlayerPack.error.message}</p>}
      </article>
    </div>

    {playerPackReview && <article className="extension-update-review player-pack-review" aria-labelledby="player-pack-review-heading">
      <div>
        <p className="eyebrow">Reviewed player pack</p>
        <h3 id="player-pack-review-heading">{playerPackReview.file_name}</h3>
        <p>{Object.entries(playerPackReview.dependencies).map(([name, version]) => `${name} ${version}`).join(" · ")}</p>
      </div>
      <div className="extension-columns">
        <div>
          <h4>Included automatically</h4>
          {playerPackReview.included.length
            ? <ul>{playerPackReview.included.map(item => <li key={item.file_name}><strong>{item.file_name}</strong></li>)}</ul>
            : <p>No client jars can be downloaded automatically.</p>}
        </div>
        <div>
          <h4>Manual requirements</h4>
          {playerPackReview.manual_requirements.length
            ? <ul>{playerPackReview.manual_requirements.map(item => <li key={item.file_name}><strong>{item.file_name}</strong><span>{item.reason}</span></li>)}</ul>
            : <p>No manual files are required.</p>}
        </div>
      </div>
      {playerPackReview.excluded.length > 0 && <div>
        <h4>Excluded as server-only</h4>
        <ul>{playerPackReview.excluded.map(item => <li key={item.file_name}><strong>{item.file_name}</strong><span>{item.reason}</span></li>)}</ul>
      </div>}
      {playerPackReview.disclosures.map(item => <p className="warning" key={`${item.file_name}-${item.message}`}>{item.file_name}: {item.message}</p>)}
      <small>The download is tied to this exact review. If the loadout changes, Blockstead asks you to review again.</small>
    </article>}

    {downloadNotice && <p className="success" role="status">{downloadNotice}</p>}
    {downloadError && <p className="error" role="alert">{downloadError}</p>}

    {lockfileReview && <article className="extension-update-review" aria-labelledby="lockfile-review-heading">
      <div>
        <p className="eyebrow">Review only</p>
        <h3 id="lockfile-review-heading">Lockfile comparison</h3>
        <p>{lockfileReview.distribution} {lockfileReview.minecraft_version}{lockfileReview.loader_version ? ` · loader ${lockfileReview.loader_version}` : ""}</p>
      </div>
      {lockfileReview.changes.length > 0
        ? <ul>{lockfileReview.changes.map((change, index) => <li key={`${change.file_name}-${index}`}>
          <strong>{change.file_name}</strong>
          <span>{change.action} · {change.detail}</span>
        </li>)}</ul>
        : <p className="success">This server already matches the reviewed loadout.</p>}
      {lockfileReview.exclusions.length > 0 && <div>
        <h4>Excluded</h4>
        <ul>{lockfileReview.exclusions.map(item => <li key={item}>{item}</li>)}</ul>
      </div>}
      {lockfileReview.manual_requirements.length > 0 && <div>
        <h4>Manual requirements</h4>
        <ul>{lockfileReview.manual_requirements.map(item => <li key={item}>{item}</li>)}</ul>
      </div>}
      {lockfileReview.warnings.map(item => <p className="warning" key={item}>{item}</p>)}
      {lockfileReview.blockers.map(item => <p className="error" key={item}>{item}</p>)}
      <small>This review expires in {Math.max(1, Math.ceil(lockfileReview.expires_in_seconds / 60))} minutes.</small>
      <small>No changes have been applied.</small>
    </article>}
  </section>;
}
