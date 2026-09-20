import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ApiRequestError,
  api,
  type MaintenanceBooking,
  type MaintenanceCatalog,
  type MaintenanceChangeId,
  type MaintenancePlan,
  type ServerUpgradeResult,
  type UpgradeCandidate,
  type UpgradeReview,
} from "../../api/client";
import { Button } from "../../components/Button";
import { LoaderMigrationPanel } from "./LoaderMigrationPanel";

const findingStatusLabels = {
  ready: "Ready",
  attention: "Needs attention",
  blocked: "Stop",
  unknown: "Could not check",
  info: "Information",
} as const;

const findingStatusMarks = {
  ready: "✓",
  attention: "!",
  blocked: "✕",
  unknown: "?",
  info: "i",
} as const;

const requirementLabels = {
  required: "Required",
  recommended: "Recommended",
  not_needed: "Already satisfied",
} as const;

const readinessLabels = {
  ready: "Safe to do now",
  ready_with_warnings: "Possible, with things to know",
  blocked: "Not safe yet",
  not_applicable: "Nothing to change",
} as const;

const stepLabels = {
  patch: "Patch release",
  minor: "Minor release",
  major: "Major release",
  unknown: "Unrecognised version",
} as const;

/** Two hours out, rounded to the hour: a sane default for "later tonight". */
function defaultRunAt() {
  const when = new Date(Date.now() + 2 * 60 * 60 * 1000);
  when.setMinutes(0, 0, 0);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}T${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

/** Paper builds and Fabric loader versions can create multiple targets per release. */
function upgradeCandidateKey(candidate: UpgradeCandidate) {
  return `${candidate.minecraft_version}::${candidate.paper_build ?? "auto"}::${candidate.loader_version ?? "auto"}`;
}

function paperBuildLabel(candidate: UpgradeCandidate) {
  return candidate.paper_build == null ? "" : `Paper build ${candidate.paper_build}`;
}

function fabricLoaderLabel(candidate: UpgradeCandidate) {
  return candidate.loader_version == null ? "" : `Fabric loader ${candidate.loader_version}`;
}

function candidateArtifactIsPinned(
  distribution: string,
  candidate: UpgradeCandidate,
  candidateKey: string,
  selectedKey: string,
  reviewedKey: string | null,
  plan: MaintenancePlan | null,
) {
  if (distribution !== "paper" && distribution !== "fabric") return true;
  const targetIsCrossVersion = distribution === "paper"
    ? candidate.paper_build == null
    : candidate.loader_version == null;
  if (!targetIsCrossVersion) return true;
  if (selectedKey !== candidateKey || reviewedKey !== candidateKey || plan == null) return false;
  if (plan.upgrade_target !== candidate.minecraft_version) return false;
  return distribution === "paper"
    ? plan.upgrade_paper_build != null
    : plan.upgrade_loader_version != null;
}

type PreflightInput = {
  id: MaintenanceChangeId;
  minecraftVersion?: string;
  paperBuild?: number;
  loaderVersion?: string;
  targetKey?: string;
};

type ScheduleInput = {
  planId: string;
  changeId: MaintenanceChangeId;
  minecraftVersion?: string;
  paperBuild?: number;
  loaderVersion?: string;
  targetKey?: string;
};

function CatalogFailure({ error, retry }: { error: Error; retry: () => void }) {
  const request = error instanceof ApiRequestError ? error : null;
  const title = request?.status === 404
    ? "Maintenance needs a matching Blockstead update"
    : request?.status === 401
      ? "Sign in again to open Maintenance"
      : request?.status && request.status >= 500
        ? "Blockstead hit an internal error"
        : "Blockstead could not reach the maintenance service";
  const detail = request?.status === 404
    ? "The dashboard and backend appear to be different versions. Update Blockstead, restart its service, and try again. This is an application problem, not a Minecraft or mod error."
    : request?.status === 401
      ? "Your Blockstead session expired. The sign-in screen should open automatically."
      : request?.status && request.status >= 500
        ? `${error.message} Your Minecraft server and files were not changed.`
        : `${error.message} Check that the Blockstead service is running, then retry.`;
  return <div className="query-error maintenance-load-error" role="alert">
    <strong>{title}</strong>
    <p>{detail}</p>
    <div className="maintenance-actions">
      <Button className="button--secondary button--small" onClick={retry}>Try again</Button>
      <Link className="button button--quiet button--small" to="/system#updates">Check for Blockstead updates</Link>
      <Link className="button button--quiet button--small" to="/system#diagnostics">Open diagnostics</Link>
    </div>
  </div>;
}

export function MaintenancePanel({ profileId }: { profileId: string }) {
  const client = useQueryClient();
  const [changeId, setChangeId] = useState<MaintenanceChangeId | "">("");
  const [runAt, setRunAt] = useState(defaultRunAt);
  const [onlyWhenEmpty, setOnlyWhenEmpty] = useState(true);
  const [selectedTargetKey, setSelectedTargetKey] = useState("");
  // The selected target key includes Paper's build number. Keep it separately
  // from the API's plan so an old mutation result cannot become actionable
  // after a target change.
  const [reviewedTarget, setReviewedTarget] = useState<string | null>(null);
  const [reviewActive, setReviewActive] = useState(false);
  const [booking, setBooking] = useState<MaintenanceBooking | null>(null);
  const [staleNotice, setStaleNotice] = useState("");
  const [freshPlan, setFreshPlan] = useState<MaintenancePlan | null>(null);
  const [appliedUpgrade, setAppliedUpgrade] = useState<ServerUpgradeResult | null>(null);
  const [recoveryNotice, setRecoveryNotice] = useState("");
  const selectedTargetKeyRef = useRef("");
  const reviewTokenRef = useRef(0);

  const catalog = useQuery({
    queryKey: ["maintenance-changes"],
    queryFn: () => api<MaintenanceCatalog>("/maintenance/changes"),
  });
  const change = catalog.data?.changes.find(entry => entry.id === changeId);

  // Only the upgrade review needs the published release list, so only it asks.
  const upgrades = useQuery({
    queryKey: ["maintenance-upgrades", profileId],
    queryFn: () => api<UpgradeReview>(`/profiles/${profileId}/maintenance/upgrades`),
    enabled: changeId === "server_upgrade",
  });
  const selectedCandidate = upgrades.data?.candidates.find(candidate => upgradeCandidateKey(candidate) === selectedTargetKey);

  function resetResult() {
    setBooking(null);
    setStaleNotice("");
    setFreshPlan(null);
    setRecoveryNotice("");
    setReviewedTarget(null);
    setReviewActive(false);
  }

  const preflight = useMutation({
    mutationFn: (input: PreflightInput) => {
      const body: {
        change_id: MaintenanceChangeId;
        minecraft_version?: string;
        paper_build?: number;
        loader_version?: string;
      } = {
        change_id: input.id,
      };
      if (input.id === "server_upgrade" && input.minecraftVersion) {
        body.minecraft_version = input.minecraftVersion;
      }
      if (input.id === "server_upgrade" && input.paperBuild != null) {
        body.paper_build = input.paperBuild;
      }
      if (input.id === "server_upgrade" && input.loaderVersion != null) {
        body.loader_version = input.loaderVersion;
      }
      return api<MaintenancePlan>(`/profiles/${profileId}/maintenance/preflight`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onMutate: input => {
      const token = ++reviewTokenRef.current;
      resetResult();
      setReviewedTarget(input.id === "server_upgrade" ? input.targetKey ?? null : null);
      setReviewActive(true);
      return { token };
    },
    // The review is recorded in Activity, so the feed is no longer current.
    onSuccess: (_result, _input, context) => {
      if (context?.token === reviewTokenRef.current) {
        void client.invalidateQueries({ queryKey: ["activity"] });
      }
    },
  });
  const reviewed = freshPlan ?? preflight.data;
  const planTargetMatchesSelection = reviewed?.change.id !== "server_upgrade"
    || (
      selectedTargetKey
        ? reviewedTarget === selectedTargetKey
          && selectedCandidate != null
          // A missing target is allowed to remain visible as a diagnostic
          // blocked review for older backends. Apply requires an exact echoed
          // target below.
          && (reviewed.upgrade_target == null || reviewed.upgrade_target === selectedCandidate.minecraft_version)
          // A newer Paper version may start from a candidate without a known
          // build; the backend resolves and echoes a stable build in the plan.
          && (
            selectedCandidate.paper_build == null
              || reviewed.upgrade_paper_build == null
              || reviewed.upgrade_paper_build === selectedCandidate.paper_build
          )
          // A newer Fabric version may start from a candidate without a known
          // loader; the backend resolves and echoes a stable loader in the plan.
          && (
            selectedCandidate.loader_version == null
              || reviewed.upgrade_loader_version == null
              || reviewed.upgrade_loader_version === selectedCandidate.loader_version
          )
        : reviewedTarget === null
    );
  const plan = reviewed?.profile_id === profileId
    && (reviewed.change.id !== "server_upgrade" || reviewActive)
    && reviewed.change.id === changeId
    && planTargetMatchesSelection
    ? reviewed
    : null;

  const schedule = useMutation({
    mutationFn: (input: ScheduleInput) => {
      const body: {
        change_id: MaintenanceChangeId;
        plan_id: string;
        run_at: string;
        only_when_empty: boolean;
        minecraft_version?: string;
        paper_build?: number;
        loader_version?: string;
      } = {
        change_id: input.changeId,
        plan_id: input.planId,
        run_at: runAt,
        only_when_empty: onlyWhenEmpty,
      };
      if (input.changeId === "server_upgrade" && input.minecraftVersion) {
        body.minecraft_version = input.minecraftVersion;
      }
      if (input.changeId === "server_upgrade" && input.paperBuild != null) {
        body.paper_build = input.paperBuild;
      }
      if (input.changeId === "server_upgrade" && input.loaderVersion != null) {
        body.loader_version = input.loaderVersion;
      }
      return api<MaintenanceBooking>(`/profiles/${profileId}/maintenance/schedule`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onMutate: () => ({ token: reviewTokenRef.current }),
    onSuccess: (result, _input, context) => {
      if (context?.token !== reviewTokenRef.current) return;
      setStaleNotice("");
      setFreshPlan(null);
      setBooking(result);
      void client.invalidateQueries();
    },
    onError: (error, input, context) => {
      if (context?.token !== reviewTokenRef.current) return;
      if (input.changeId === "server_upgrade" && input.targetKey !== selectedTargetKeyRef.current) {
        setFreshPlan(null);
        setReviewedTarget(null);
        setReviewActive(false);
        return;
      }
      setBooking(null);
      // A stale plan is a re-review, not a dead end: the refusal carries the
      // current plan, so show that instead of asking the owner to start over.
      const body = error instanceof ApiRequestError ? error.body as { plan?: MaintenancePlan } : null;
      if (body?.plan) {
        if (
          input.changeId === "server_upgrade"
          && (
            (body.plan.upgrade_target != null && body.plan.upgrade_target !== input.minecraftVersion)
            || (input.paperBuild != null && body.plan.upgrade_paper_build !== input.paperBuild)
            || (input.loaderVersion != null && body.plan.upgrade_loader_version !== input.loaderVersion)
          )
        ) {
          setFreshPlan(null);
          setReviewedTarget(null);
          setReviewActive(false);
          return;
        }
        setFreshPlan(body.plan);
        setReviewedTarget(input.changeId === "server_upgrade" ? input.targetKey ?? null : null);
        setReviewActive(true);
        setStaleNotice(error.message);
      }
    },
  });
  const applyUpgrade = useMutation({
    mutationFn: (input: { version: string; planId: string; paperBuild?: number; loaderVersion?: string }) => {
      const body: {
        minecraft_version: string;
        plan_id: string;
        paper_build?: number;
        loader_version?: string;
      } = {
        minecraft_version: input.version,
        plan_id: input.planId,
      };
      if (input.paperBuild != null) body.paper_build = input.paperBuild;
      if (input.loaderVersion != null) body.loader_version = input.loaderVersion;
      return api<ServerUpgradeResult>(`/profiles/${profileId}/maintenance/upgrades/apply`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onMutate: () => ({ token: reviewTokenRef.current }),
    onSuccess: (result, _input, context) => {
      if (context?.token !== reviewTokenRef.current) return;
      // The reviewed plan has been consumed. Keep the recovery action visible,
      // but remove the old plan so it cannot be treated as actionable again.
      clearReview();
      selectedTargetKeyRef.current = "";
      setSelectedTargetKey("");
      setAppliedUpgrade(result);
      setRecoveryNotice("");
      void client.invalidateQueries();
    },
  });
  const rollbackUpgrade = useMutation({
    mutationFn: (recoveryId: string) =>
      api<{ detail: string }>(`/profiles/${profileId}/maintenance/upgrades/recovery/${recoveryId}`, {
        method: "POST",
      }),
    onSuccess: result => {
      setAppliedUpgrade(null);
      setRecoveryNotice(result.detail);
      void client.invalidateQueries();
    },
  });

  function clearReview() {
    reviewTokenRef.current += 1;
    resetResult();
    preflight.reset();
    schedule.reset();
    applyUpgrade.reset();
    rollbackUpgrade.reset();
  }

  function chooseUpgradeTarget(version: string) {
    if (version === selectedTargetKeyRef.current) return;
    selectedTargetKeyRef.current = version;
    setSelectedTargetKey(version);
    clearReview();
  }

  useEffect(() => {
    // A profile switch must not carry a reviewed plan or a target across
    // servers while the profile-scoped queries are changing.
    reviewTokenRef.current += 1;
    selectedTargetKeyRef.current = "";
    setSelectedTargetKey("");
    resetResult();
    setAppliedUpgrade(null);
    preflight.reset();
    schedule.reset();
    applyUpgrade.reset();
    rollbackUpgrade.reset();
    // The mutation reset functions are stable for the lifetime of this panel;
    // profileId is the only value that should trigger this cleanup.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId]);

  // Published candidates arrive asynchronously. Preserve an explicit choice
  // when it remains installable; otherwise use the first installable release.
  useEffect(() => {
    if (changeId !== "server_upgrade") return;
    const candidates = upgrades.data?.candidates ?? [];
    const currentIsInstallable = candidates.some(candidate => upgradeCandidateKey(candidate) === selectedTargetKey && candidate.installable);
    const firstInstallable = candidates.find(candidate => candidate.installable);
    const next = currentIsInstallable
      ? selectedTargetKey
      : firstInstallable ? upgradeCandidateKey(firstInstallable) : "";
    if (next !== selectedTargetKey) {
      selectedTargetKeyRef.current = next;
      setSelectedTargetKey(next);
    }
  }, [changeId, selectedTargetKey, upgrades.data]);

  const upgradeTargetSelectionRequired = change?.id === "server_upgrade"
    && !selectedTargetKey
    && !upgrades.error
    && (!upgrades.data
      || (
        upgrades.data.source === "available"
        && upgrades.data.up_to_date !== true
        && upgrades.data.candidates.some(candidate => candidate.installable)
      ));
  const reviewedUpgradeTargetMatches = plan?.change.id === "server_upgrade"
    && selectedCandidate != null
    && plan.upgrade_target === selectedCandidate.minecraft_version
    && (
      upgrades.data?.distribution !== "paper"
        ? plan.upgrade_paper_build == null
        : selectedCandidate.paper_build != null
          ? plan.upgrade_paper_build === selectedCandidate.paper_build
          : typeof plan.upgrade_paper_build === "number"
            && Number.isInteger(plan.upgrade_paper_build)
            && plan.upgrade_paper_build > 0
    )
    && (
      upgrades.data?.distribution !== "fabric"
        ? plan.upgrade_loader_version == null
        : selectedCandidate.loader_version != null
          ? plan.upgrade_loader_version === selectedCandidate.loader_version
          : typeof plan.upgrade_loader_version === "string"
            && plan.upgrade_loader_version.trim().length > 0
    );
  const targetMutationPending = schedule.isPending || applyUpgrade.isPending || rollbackUpgrade.isPending;
  const upgradeCandidatesLoading = change?.id === "server_upgrade" && upgrades.isFetching;

  return <section className="card maintenance-panel" aria-labelledby="maintenance-heading">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Maintenance</p>
        <h2 id="maintenance-heading">Check whether a change is safe before you make it</h2>
      </div>
    </div>
    <p className="maintenance-intro">Blockstead reads the current evidence — who is connected, whether the server is stopped, whether a backup really verifies, free disk, a pending restart, and known compatibility limits — and turns it into one readable plan. The review changes nothing on its own, and every step below is still yours to run in the workspace that owns it.</p>

    {catalog.isPending && <p className="empty-note">Opening the reviewed change list…</p>}
    {catalog.error && <CatalogFailure error={catalog.error} retry={() => void catalog.refetch()} />}

    <LoaderMigrationPanel profileId={profileId} />

    {catalog.data && <fieldset className="maintenance-changes">
      <legend>What do you want to change?</legend>
      <div className="maintenance-change-grid">
        {catalog.data.changes.map(entry => <label key={entry.id} className={changeId === entry.id ? "is-selected" : ""}>
          <input
            type="radio"
            name="maintenance-change"
            value={entry.id}
            checked={changeId === entry.id}
            disabled={targetMutationPending}
            onChange={() => {
              setChangeId(entry.id);
              selectedTargetKeyRef.current = "";
              setSelectedTargetKey("");
              clearReview();
            }}
          />
          <strong>{entry.title}</strong>
          <span>{entry.summary}</span>
          <small>{entry.requires_stopped_server ? "Stopped server only" : "Can be done while running"}{entry.destructive ? " · can affect world data" : ""}</small>
        </label>)}
      </div>
    </fieldset>}

    {changeId === "server_upgrade" && <div className="maintenance-upgrades">
      <h3>Published releases</h3>
      {upgrades.isPending && <p className="empty-note">Reading the published release list…</p>}
      {upgrades.error && <p className="error" role="alert">{upgrades.error.message}</p>}
      {upgrades.data && <>
        <p>{upgrades.data.source_detail}</p>
        {upgrades.data.distribution === "paper" && <p className="muted-note">
          Installed Paper build: {upgrades.data.current_paper_build != null
            ? `Paper build ${upgrades.data.current_paper_build}`
            : "Unknown"}
          {upgrades.data.paper_build_detail ? ` · ${upgrades.data.paper_build_detail}` : ""}
        </p>}
        {upgrades.data.distribution === "paper" && <p className="muted-note">Paper targets use stable builds; newer Minecraft releases may resolve a stable build during review.</p>}
        {upgrades.data.distribution === "fabric" && <p className="muted-note">
          Recorded Fabric loader: {upgrades.data.current_loader_version ?? "Unknown"}
          {upgrades.data.loader_version_detail
            ? ` · ${upgrades.data.loader_version_detail}`
            : " · This is a recorded profile value; the active jar was not verified."}
        </p>}
        {upgrades.data.distribution === "fabric" && <p className="muted-note">Fabric targets use stable loader releases; newer Minecraft releases may resolve a stable loader during review.</p>}
        {upgrades.data.warnings.map(warning => <p className="warning" key={warning}>{warning}</p>)}
        {upgrades.data.up_to_date === true
          && (upgrades.data.distribution !== "paper" || upgrades.data.current_paper_build != null)
          && (upgrades.data.distribution !== "fabric" || upgrades.data.current_loader_version != null)
          && <p className="success" role="status">{upgrades.data.distribution === "paper"
            ? `This server is on Minecraft ${upgrades.data.current_version}, stable Paper build ${upgrades.data.current_paper_build}, the newest published Paper release.`
            : upgrades.data.distribution === "fabric"
              ? `This profile records Minecraft ${upgrades.data.current_version} with Fabric loader ${upgrades.data.current_loader_version}. The active Fabric jar was not verified.`
              : `This server is on ${upgrades.data.current_version}, the newest published ${upgrades.data.distribution_label} release.`}</p>}
        {upgrades.data.up_to_date === true && upgrades.data.distribution === "paper" && upgrades.data.current_paper_build == null
          && <p className="warning" role="status">This server's Paper build is unknown, so Blockstead cannot confirm it is on the newest stable Paper build.</p>}
        {upgrades.data.up_to_date === true && upgrades.data.distribution === "fabric" && upgrades.data.current_loader_version == null
          && <p className="warning" role="status">This server's Fabric loader version is unknown, so Blockstead cannot confirm it is on the newest stable Fabric loader.</p>}
        {upgrades.data.candidates.length > 0 && <ul className="maintenance-releases" aria-label="Newer published releases">
          {upgrades.data.candidates.map(candidate => {
            const candidateKey = upgradeCandidateKey(candidate);
            const buildLabel = paperBuildLabel(candidate);
            const loaderLabel = fabricLoaderLabel(candidate);
            const artifactIsPinned = candidateArtifactIsPinned(
              upgrades.data.distribution,
              candidate,
              candidateKey,
              selectedTargetKey,
              reviewedTarget,
              plan,
            );
            const candidateCanInstall = candidate.installable && artifactIsPinned;
            const stepLabel = upgrades.data.distribution === "paper" && candidate.minecraft_version === upgrades.data.current_version
              ? "Paper build update"
              : upgrades.data.distribution === "fabric" && candidate.minecraft_version === upgrades.data.current_version
                ? "Fabric loader update"
              : stepLabels[candidate.step];
            return <li key={candidateKey} className={`${candidateCanInstall ? "is-installable" : ""}${selectedTargetKey === candidateKey ? " is-selected" : ""}`}>
            <div>
              <small>{stepLabel}{candidate.required_java_major ? ` · needs Java ${candidate.required_java_major}` : ""}{buildLabel ? ` · ${buildLabel}` : loaderLabel ? ` · ${loaderLabel}` : upgrades.data.distribution === "paper" ? " · stable Paper build selected during review" : upgrades.data.distribution === "fabric" ? " · stable Fabric loader selected during review" : ""}</small>
              <label>
                <input
                  type="radio"
                  name="minecraft-upgrade-target"
                  value={candidateKey}
                  checked={selectedTargetKey === candidateKey}
                  disabled={!candidate.installable || targetMutationPending || upgradeCandidatesLoading}
                  onChange={() => chooseUpgradeTarget(candidateKey)}
                  aria-label={`Upgrade to Minecraft ${candidate.minecraft_version}${buildLabel ? `, ${buildLabel}` : loaderLabel ? `, ${loaderLabel}` : ""}`}
                />
                <strong>{candidate.minecraft_version}</strong>
              </label>
              <p>{candidate.detail}</p>
            </div>
            <span>{candidate.installable
              ? artifactIsPinned
                ? selectedTargetKey === candidateKey
                  ? "Blockstead can install · selected target"
                  : "Blockstead can install"
                : selectedTargetKey === candidateKey
                  ? "Eligible for preflight · selected target"
                  : "Eligible for preflight"
              : "Not installable here"}</span>
          </li>;
          })}
        </ul>}
        <p className="muted-note">{upgrades.data.install_detail}</p>
        {upgradeTargetSelectionRequired && <p className="warning" role="status">Choose an installable published release before running the preflight.</p>}
      </>}
    </div>}

    {change && <div className="maintenance-review">
      <h3>Blockstead will check</h3>
      <ul>{change.checks.map(item => <li key={item}>{item}</li>)}</ul>
      <div className="maintenance-actions">
        <Button
          disabled={preflight.isPending || upgradeTargetSelectionRequired || targetMutationPending || upgradeCandidatesLoading}
          onClick={() => preflight.mutate({
            id: change.id,
            ...(change.id === "server_upgrade" && selectedCandidate ? {
              minecraftVersion: selectedCandidate.minecraft_version,
              targetKey: selectedTargetKey,
              ...(selectedCandidate.paper_build != null ? { paperBuild: selectedCandidate.paper_build } : {}),
              ...(selectedCandidate.loader_version != null ? { loaderVersion: selectedCandidate.loader_version } : {}),
            } : {}),
          })}
        >
          {preflight.isPending ? "Checking…" : "Run the preflight"}
        </Button>
      </div>
      {preflight.error && <p className="error" role="alert">{preflight.error.message}</p>}
    </div>}

    {plan && <>
      <div className={`maintenance-outcome maintenance-outcome--${plan.readiness}`} role="status">
        <p className="eyebrow">{readinessLabels[plan.readiness]}</p>
        <h3>{plan.headline}</h3>
        <p>{plan.detail}</p>
      </div>

      <ul className="maintenance-findings" aria-label="Preflight findings">
        {plan.findings.map(item => <li key={item.id} className={`maintenance-finding maintenance-finding--${item.status}`}>
          <span aria-hidden="true">{findingStatusMarks[item.status]}</span>
          <div>
            <small>{findingStatusLabels[item.status]}</small>
            <strong>{item.label}</strong>
            <p>{item.detail}</p>
            {item.recommendation && <p className="maintenance-recommendation">{item.recommendation}</p>}
          </div>
        </li>)}
      </ul>

      {plan.readiness !== "not_applicable" && <div className="maintenance-protection">
        <h3>Protection point</h3>
        <p>{plan.protection.verified
          ? `Blockstead re-checked this backup against its manifest and recorded checksum just now. ${plan.protection.detail}`
          : `There is no verified way back from this change yet. ${plan.protection.detail}`}</p>
        <Link className="button button--secondary" to={`/servers/${plan.profile_id}/backups`}>Open Backups</Link>
      </div>}

      {plan.readiness === "blocked" && <div className="maintenance-blocked" role="alert">
        <h3>Resolve this first</h3>
        <ul>{plan.blockers.map(blocker => <li key={blocker}>{blocker}</li>)}</ul>
        <p>Blockstead is not showing a plan for a change it cannot call safe. Nothing has been changed.</p>
      </div>}

      {!["blocked", "not_applicable"].includes(plan.readiness) && <>
        <ol className="maintenance-steps" aria-label="Reviewed plan">
          {plan.steps.map(step => <li key={step.id} className={`maintenance-step maintenance-step--${step.requirement}`}>
            <div>
              <small>{requirementLabels[step.requirement]}</small>
              <strong>{step.label}</strong>
              <p>{step.detail}</p>
            </div>
            {step.route && <Link className="button button--quiet" to={step.route}>Open</Link>}
          </li>)}
        </ol>

        <div className="maintenance-restart">
          <h3>Stop and restart expectation</h3>
          <p>{plan.restart_detail}</p>
        </div>

        {plan.change.id === "server_upgrade" && selectedCandidate?.installable && <div className="maintenance-apply">
          <h3>Apply the reviewed upgrade</h3>
          <p>Blockstead will replace only the stopped server’s active launch file, then validate its launch plan. The previous launch file is retained. The world is never rolled back automatically.</p>
          {selectedCandidate.paper_build != null && <p className="muted-note">Target: {selectedCandidate.minecraft_version} · Paper build {selectedCandidate.paper_build}</p>}
          {upgrades.data?.distribution === "paper" && selectedCandidate.paper_build == null && plan.upgrade_paper_build != null && <p className="muted-note">Blockstead pinned Paper build {plan.upgrade_paper_build} for this Minecraft release.</p>}
          {selectedCandidate.loader_version != null && <p className="muted-note">Target: {selectedCandidate.minecraft_version} · Fabric loader {selectedCandidate.loader_version}</p>}
          {upgrades.data?.distribution === "fabric" && selectedCandidate.loader_version == null && plan.upgrade_loader_version != null && <p className="muted-note">Blockstead pinned Fabric loader {plan.upgrade_loader_version} for this Minecraft release.</p>}
          {plan.protection.verified && (plan.protection.age_hours ?? 25) <= 24
            ? <p className="success">The required fresh protection point verifies.</p>
            : <p className="warning">Create a fresh verified backup and run this preflight again before applying the upgrade.</p>}
          {!reviewedUpgradeTargetMatches && <p className="warning">Run the preflight again for the selected release before applying this upgrade.</p>}
          <div className="maintenance-actions">
            {(!plan.protection.verified || (plan.protection.age_hours ?? 25) > 24) && <Link className="button button--secondary" to={`/servers/${profileId}/backups`}>Create a backup</Link>}
            <Button
              disabled={targetMutationPending || upgradeCandidatesLoading || !reviewedUpgradeTargetMatches || !plan.protection.verified || (plan.protection.age_hours ?? 25) > 24}
              onClick={() => applyUpgrade.mutate({
                version: plan.upgrade_target ?? selectedCandidate.minecraft_version,
                planId: plan.plan_id,
                ...(plan.upgrade_paper_build != null ? { paperBuild: plan.upgrade_paper_build } : {}),
                ...(plan.upgrade_loader_version != null ? { loaderVersion: plan.upgrade_loader_version } : {}),
              })}
            >
              {applyUpgrade.isPending
                ? "Applying and validating…"
                : `Upgrade to ${selectedCandidate.minecraft_version}${selectedCandidate.paper_build != null ? ` · Paper build ${selectedCandidate.paper_build}` : selectedCandidate.loader_version != null ? ` · Fabric loader ${selectedCandidate.loader_version}` : ""}`}
            </Button>
          </div>
          {applyUpgrade.error && <p className="error" role="alert">{applyUpgrade.error.message}</p>}
        </div>}

        <div className="maintenance-booking">
          <h3>Book a window for this plan</h3>
          <p>Blockstead can stop this server at a time you choose, after a verified backup. Applying the change itself stays yours to do — nothing is installed automatically.</p>
          <div className="maintenance-booking-controls">
            <label>
              <span>Stop at</span>
              <input
                type="datetime-local"
                aria-label="Maintenance window time"
                value={runAt}
                onChange={event => setRunAt(event.target.value)}
              />
            </label>
            <label className="maintenance-booking-toggle">
              <input
                type="checkbox"
                checked={onlyWhenEmpty}
                onChange={event => setOnlyWhenEmpty(event.target.checked)}
              />
              <span>Only when nobody is playing</span>
            </label>
            <Button
              disabled={targetMutationPending || upgradeCandidatesLoading || !runAt || (plan.change.id === "server_upgrade" && !reviewedUpgradeTargetMatches)}
              onClick={() => schedule.mutate({
                planId: plan.plan_id,
                changeId: plan.change.id,
                ...(plan.change.id === "server_upgrade" && selectedCandidate ? {
                  minecraftVersion: plan.upgrade_target ?? selectedCandidate.minecraft_version,
                  targetKey: selectedTargetKey,
                  ...(plan.upgrade_paper_build != null ? { paperBuild: plan.upgrade_paper_build } : {}),
                  ...(plan.upgrade_loader_version != null ? { loaderVersion: plan.upgrade_loader_version } : {}),
                } : {}),
              })}
            >
              {schedule.isPending ? "Booking…" : "Schedule this plan"}
            </Button>
          </div>
          {staleNotice && <p className="warning" role="alert">{staleNotice} The review above is the current one — check it, then book again.</p>}
          {schedule.error && !staleNotice && <p className="error" role="alert">{schedule.error.message}</p>}
          {booking && <p className="success" role="status">{booking.detail}</p>}
        </div>
      </>}

      <p className="muted-note">Reviewed {new Date(plan.reviewed_at).toLocaleString()} · plan {plan.plan_id}. This review reflects the evidence at that moment; run it again if the server has been used since.</p>
    </>}

    {appliedUpgrade && <div className="maintenance-recovery" role="status">
      <p>{appliedUpgrade.detail}</p>
      <Button
        className="button--secondary"
        disabled={rollbackUpgrade.isPending}
        onClick={() => rollbackUpgrade.mutate(appliedUpgrade.recovery_id)}
      >
        {rollbackUpgrade.isPending ? "Restoring launch file…" : "Restore previous launch file"}
      </Button>
    </div>}
    {rollbackUpgrade.error && <p className="error" role="alert">{rollbackUpgrade.error.message}</p>}
    {recoveryNotice && <p className="success" role="status">{recoveryNotice}</p>}
  </section>;
}
