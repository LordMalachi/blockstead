import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  api,
  type MaintenanceCatalog,
  type MaintenanceChangeId,
  type MaintenancePlan,
} from "../../api/client";
import { Button } from "../../components/Button";

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
} as const;

export function MaintenancePanel({ profileId }: { profileId: string }) {
  const client = useQueryClient();
  const [changeId, setChangeId] = useState<MaintenanceChangeId | "">("");

  const catalog = useQuery({
    queryKey: ["maintenance-changes"],
    queryFn: () => api<MaintenanceCatalog>("/maintenance/changes"),
  });
  const change = catalog.data?.changes.find(entry => entry.id === changeId);

  const preflight = useMutation({
    mutationFn: (id: MaintenanceChangeId) =>
      api<MaintenancePlan>(`/profiles/${profileId}/maintenance/preflight`, {
        method: "POST",
        body: JSON.stringify({ change_id: id }),
      }),
    // The review is recorded in Activity, so the feed is no longer current.
    onSuccess: () => void client.invalidateQueries({ queryKey: ["activity"] }),
  });
  const plan = preflight.data?.change.id === changeId ? preflight.data : null;

  return <section className="card maintenance-panel" aria-labelledby="maintenance-heading">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Maintenance</p>
        <h2 id="maintenance-heading">Check whether a change is safe before you make it</h2>
      </div>
    </div>
    <p className="maintenance-intro">Blockstead reads the current evidence — who is connected, whether the server is stopped, whether a backup really verifies, free disk, a pending restart, and known compatibility limits — and turns it into one readable plan. The review changes nothing on its own, and every step below is still yours to run in the workspace that owns it.</p>

    {catalog.isPending && <p className="empty-note">Opening the reviewed change list…</p>}
    {catalog.error && <p className="error" role="alert">{catalog.error.message}</p>}

    {catalog.data && <fieldset className="maintenance-changes">
      <legend>What do you want to change?</legend>
      <div className="maintenance-change-grid">
        {catalog.data.changes.map(entry => <label key={entry.id} className={changeId === entry.id ? "is-selected" : ""}>
          <input
            type="radio"
            name="maintenance-change"
            value={entry.id}
            checked={changeId === entry.id}
            onChange={() => setChangeId(entry.id)}
          />
          <strong>{entry.title}</strong>
          <span>{entry.summary}</span>
          <small>{entry.requires_stopped_server ? "Stopped server only" : "Can be done while running"}{entry.destructive ? " · can affect world data" : ""}</small>
        </label>)}
      </div>
    </fieldset>}

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

      <div className="maintenance-protection">
        <h3>Protection point</h3>
        <p>{plan.protection.verified
          ? `Blockstead re-checked this backup against its manifest and recorded checksum just now. ${plan.protection.detail}`
          : `There is no verified way back from this change yet. ${plan.protection.detail}`}</p>
        <Link className="button button--secondary" to={`/servers/${plan.profile_id}/backups`}>Open Backups</Link>
      </div>

      {plan.readiness === "blocked"
        ? <div className="maintenance-blocked" role="alert">
            <h3>Resolve this first</h3>
            <ul>{plan.blockers.map(blocker => <li key={blocker}>{blocker}</li>)}</ul>
            <p>Blockstead is not showing a plan for a change it cannot call safe. Nothing has been changed.</p>
          </div>
        : <ol className="maintenance-steps" aria-label="Reviewed plan">
            {plan.steps.map(step => <li key={step.id} className={`maintenance-step maintenance-step--${step.requirement}`}>
              <div>
                <small>{requirementLabels[step.requirement]}</small>
                <strong>{step.label}</strong>
                <p>{step.detail}</p>
              </div>
              {step.route && <Link className="button button--quiet" to={step.route}>Open</Link>}
            </li>)}
          </ol>}

      <div className="maintenance-restart">
        <h3>Stop and restart expectation</h3>
        <p>{plan.restart_detail}</p>
      </div>

      <p className="muted-note">Reviewed {new Date(plan.reviewed_at).toLocaleString()} · plan {plan.plan_id}. This review reflects the evidence at that moment; run it again if the server has been used since.</p>
    </>}
  </section>;
}
