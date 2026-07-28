import { useState } from "react";
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
  const [booking, setBooking] = useState<MaintenanceBooking | null>(null);
  const [staleNotice, setStaleNotice] = useState("");
  const [freshPlan, setFreshPlan] = useState<MaintenancePlan | null>(null);
  const [appliedUpgrade, setAppliedUpgrade] = useState<ServerUpgradeResult | null>(null);
  const [recoveryNotice, setRecoveryNotice] = useState("");

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

  function resetResult() {
    setBooking(null);
    setStaleNotice("");
    setFreshPlan(null);
    setAppliedUpgrade(null);
    setRecoveryNotice("");
  }

  const preflight = useMutation({
    mutationFn: (id: MaintenanceChangeId) =>
      api<MaintenancePlan>(`/profiles/${profileId}/maintenance/preflight`, {
        method: "POST",
        body: JSON.stringify({ change_id: id }),
      }),
    onMutate: resetResult,
    // The review is recorded in Activity, so the feed is no longer current.
    onSuccess: () => void client.invalidateQueries({ queryKey: ["activity"] }),
  });
  const reviewed = freshPlan ?? preflight.data;
  const plan = reviewed?.change.id === changeId ? reviewed : null;

  const schedule = useMutation({
    mutationFn: (input: { planId: string; changeId: MaintenanceChangeId }) =>
      api<MaintenanceBooking>(`/profiles/${profileId}/maintenance/schedule`, {
        method: "POST",
        body: JSON.stringify({
          change_id: input.changeId,
          plan_id: input.planId,
          run_at: runAt,
          only_when_empty: onlyWhenEmpty,
        }),
      }),
    onSuccess: result => {
      setStaleNotice("");
      setFreshPlan(null);
      setBooking(result);
      void client.invalidateQueries();
    },
    onError: error => {
      setBooking(null);
      // A stale plan is a re-review, not a dead end: the refusal carries the
      // current plan, so show that instead of asking the owner to start over.
      const body = error instanceof ApiRequestError ? error.body as { plan?: MaintenancePlan } : null;
      if (body?.plan) {
        setFreshPlan(body.plan);
        setStaleNotice(error.message);
      }
    },
  });
  const applyUpgrade = useMutation({
    mutationFn: (input: { version: string; planId: string }) =>
      api<ServerUpgradeResult>(`/profiles/${profileId}/maintenance/upgrades/apply`, {
        method: "POST",
        body: JSON.stringify({
          minecraft_version: input.version,
          plan_id: input.planId,
        }),
      }),
    onSuccess: result => {
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
            onChange={() => { setChangeId(entry.id); resetResult(); }}
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
        {upgrades.data.warnings.map(warning => <p className="warning" key={warning}>{warning}</p>)}
        {upgrades.data.up_to_date === true && <p className="success" role="status">This server is on {upgrades.data.current_version}, the newest published {upgrades.data.distribution_label} release.</p>}
        {upgrades.data.candidates.length > 0 && <ul className="maintenance-releases" aria-label="Newer published releases">
          {upgrades.data.candidates.slice(0, 8).map(candidate => <li key={candidate.minecraft_version} className={candidate.installable ? "is-installable" : ""}>
            <div>
              <small>{stepLabels[candidate.step]}{candidate.required_java_major ? ` · needs Java ${candidate.required_java_major}` : ""}</small>
              <strong>{candidate.minecraft_version}</strong>
              <p>{candidate.detail}</p>
            </div>
            <span>{candidate.installable ? "Blockstead can install" : "Not installable here"}</span>
          </li>)}
        </ul>}
        <p className="muted-note">{upgrades.data.install_detail}</p>
      </>}
    </div>}

    {change && <div className="maintenance-review">
      <h3>Blockstead will check</h3>
      <ul>{change.checks.map(item => <li key={item}>{item}</li>)}</ul>
      <div className="maintenance-actions">
        <Button disabled={preflight.isPending} onClick={() => preflight.mutate(change.id)}>
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

        {plan.change.id === "server_upgrade" && upgrades.data?.candidates[0]?.installable && <div className="maintenance-apply">
          <h3>Apply the reviewed upgrade</h3>
          <p>Blockstead will replace only the stopped server’s active launch file, then validate its launch plan. The previous launch file is retained. The world is never rolled back automatically.</p>
          {plan.protection.verified && (plan.protection.age_hours ?? 25) <= 24
            ? <p className="success">The required fresh protection point verifies.</p>
            : <p className="warning">Create a fresh verified backup and run this preflight again before applying the upgrade.</p>}
          <div className="maintenance-actions">
            {(!plan.protection.verified || (plan.protection.age_hours ?? 25) > 24) && <Link className="button button--secondary" to={`/servers/${profileId}/backups`}>Create a backup</Link>}
            <Button
              disabled={applyUpgrade.isPending || !plan.protection.verified || (plan.protection.age_hours ?? 25) > 24}
              onClick={() => applyUpgrade.mutate({
                version: upgrades.data.candidates[0].minecraft_version,
                planId: plan.plan_id,
              })}
            >
              {applyUpgrade.isPending ? "Applying and validating…" : `Upgrade to ${upgrades.data.candidates[0].minecraft_version}`}
            </Button>
          </div>
          {applyUpgrade.error && <p className="error" role="alert">{applyUpgrade.error.message}</p>}
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
              disabled={schedule.isPending || !runAt}
              onClick={() => schedule.mutate({ planId: plan.plan_id, changeId: plan.change.id })}
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
  </section>;
}
