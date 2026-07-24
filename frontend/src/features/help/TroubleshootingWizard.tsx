import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  api,
  type Profile,
  type TroubleshootingAction,
  type TroubleshootingAssessment,
  type TroubleshootingCatalog,
  type TroubleshootingProblemId,
} from "../../api/client";
import { Button } from "../../components/Button";

type Stage = "problem" | "checks" | "results";

const PLAYER_PATTERN = /^[A-Za-z0-9_]{3,16}$/;

const statusLabels = {
  passed: "Passed",
  flagged: "Needs attention",
  unknown: "Could not check",
  info: "Information",
} as const;

export function TroubleshootingWizard({
  profiles,
  suggestedProfileId,
}: {
  profiles: Profile[];
  suggestedProfileId?: string;
}) {
  const initialProfile = suggestedProfileId ?? (profiles.length === 1 ? profiles[0]?.id : "");
  const [profileId, setProfileId] = useState(initialProfile ?? "");
  const [problemId, setProblemId] = useState<TroubleshootingProblemId | "">("");
  const [playerName, setPlayerName] = useState("");
  const [stage, setStage] = useState<Stage>("problem");
  const [pendingAction, setPendingAction] = useState<TroubleshootingAction | null>(null);
  const [repairResult, setRepairResult] = useState("");

  useEffect(() => {
    if (!profileId && initialProfile) setProfileId(initialProfile);
  }, [initialProfile, profileId]);

  const catalog = useQuery({
    queryKey: ["troubleshooting-catalog"],
    queryFn: () => api<TroubleshootingCatalog>("/troubleshooting/problems"),
  });
  const problem = catalog.data?.problems.find(entry => entry.id === problemId);
  const selectedProfile = profiles.find(profile => profile.id === profileId);

  const assessment = useMutation({
    mutationFn: (input: { profileId: string; problemId: TroubleshootingProblemId; playerName: string }) =>
      api<TroubleshootingAssessment>(`/profiles/${input.profileId}/troubleshooting/assess`, {
        method: "POST",
        body: JSON.stringify({
          problem_id: input.problemId,
          player_name: input.problemId === "player_cannot_join" ? input.playerName : null,
        }),
      }),
    onSuccess: () => setStage("results"),
  });

  const repair = useMutation({
    mutationFn: async (action: TroubleshootingAction) =>
      api<{ status?: string; detail: string }>(`/profiles/${profileId}/troubleshooting/repair`, {
        method: "POST",
        body: JSON.stringify({
          action_id: action.id,
          player_name: action.id === "enable_lan" ? null : playerName,
        }),
      }),
    onSuccess: result => {
      setPendingAction(null);
      setRepairResult(result.detail);
      window.setTimeout(() => runAssessment(false), 700);
    },
  });

  const sourcesById = useMemo(
    () => new Map(catalog.data?.sources.map(source => [source.id, source]) ?? []),
    [catalog.data],
  );
  const playerValid = !problem?.requires_player_name || PLAYER_PATTERN.test(playerName);

  function runAssessment(clearRepairResult = true) {
    if (!profileId || !problemId || !playerValid) return;
    if (clearRepairResult) setRepairResult("");
    assessment.mutate({ profileId, problemId, playerName });
  }

  function reset() {
    setProblemId("");
    setPlayerName("");
    setStage("problem");
    setRepairResult("");
    setPendingAction(null);
    assessment.reset();
    repair.reset();
  }

  if (!profiles.length) {
    return <section className="card troubleshooting-wizard" id="server-troubleshooter" aria-labelledby="troubleshooter-heading">
      <p className="eyebrow">Server troubleshooting</p>
      <h2 id="troubleshooter-heading">Choose a problem, then check the evidence</h2>
      <p>Add or import a server before running server-specific checks.</p>
      <Link className="button" to="/servers">Open server setup</Link>
    </section>;
  }

  return <section className="card troubleshooting-wizard" id="server-troubleshooter" aria-labelledby="troubleshooter-heading">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Server troubleshooting</p>
        <h2 id="troubleshooter-heading">Find and safely resolve a server problem</h2>
      </div>
      <span>Step {stage === "problem" ? 1 : stage === "checks" ? 2 : 3} of 3</span>
    </div>
    <p className="troubleshooting-intro">This is a fixed, step-by-step diagnostic. Blockstead checks only the selected server, distinguishes facts from possible causes, and never changes anything during the check.</p>

    {catalog.isPending && <p className="empty-note">Opening the tested troubleshooting guides…</p>}
    {catalog.error && <p className="error" role="alert">{catalog.error.message}</p>}

    {stage === "problem" && catalog.data && <>
      <label className="troubleshooting-server">
        <span>Which server has the problem?</span>
        <select value={profileId} onChange={event => setProfileId(event.target.value)}>
          <option value="">Choose a server</option>
          {profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name} · {profile.distribution}</option>)}
        </select>
      </label>

      <fieldset className="troubleshooting-problems">
        <legend>What is the problem?</legend>
        <div className="troubleshooting-problem-grid">
          {catalog.data.problems.map(entry => <label key={entry.id} className={problemId === entry.id ? "is-selected" : ""}>
            <input
              type="radio"
              name="troubleshooting-problem"
              value={entry.id}
              checked={problemId === entry.id}
              onChange={() => {
                setProblemId(entry.id);
                setRepairResult("");
              }}
            />
            <strong>{entry.title}</strong>
            <span>{entry.summary}</span>
          </label>)}
        </div>
      </fieldset>

      {problem?.requires_player_name && <label className="troubleshooting-player">
        <span>Which player cannot join?</span>
        <input
          aria-label="Minecraft player name"
          value={playerName}
          onChange={event => setPlayerName(event.target.value.trim())}
          placeholder="PlayerName"
          maxLength={16}
        />
        <small>Use the player’s current Minecraft name: 3–16 letters, numbers, or underscores.</small>
      </label>}

      {problem && <div className="troubleshooting-solution-preview">
        <div><h3>Blockstead can check</h3><ul>{problem.checks.map(item => <li key={item}>{item}</li>)}</ul></div>
        <div><h3>Possible solutions</h3><ul>{problem.possible_solutions.map(item => <li key={item}>{item}</li>)}</ul></div>
      </div>}

      <div className="troubleshooting-actions">
        <Button disabled={!profileId || !problem || !playerValid} onClick={() => setStage("checks")}>Continue to checks</Button>
      </div>
    </>}

    {stage === "checks" && problem && <>
      <div className="troubleshooting-review">
        <p className="eyebrow">Read-only review</p>
        <h3>Check {selectedProfile?.name} for “{problem.title}”</h3>
        <p>Blockstead will read current process state, the relevant server settings and local files, host health, and a bounded local Minecraft status response. It will not stop, restart, reconfigure, or delete anything.</p>
        <ol>{problem.checks.map(item => <li key={item}>{item}</li>)}</ol>
        <details>
          <summary>Sources behind this guide</summary>
          <ul>{problem.source_ids.map(id => {
            const source = sourcesById.get(id);
            return source ? <li key={id}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a><span>{source.publisher} · checked {source.checked_at}</span></li> : null;
          })}</ul>
        </details>
      </div>
      <div className="troubleshooting-actions">
        <Button className="button--secondary" onClick={() => setStage("problem")}>Back</Button>
        <Button disabled={assessment.isPending} onClick={() => runAssessment()}>{assessment.isPending ? "Running checks…" : "Run read-only checks"}</Button>
      </div>
      {assessment.error && <p className="error" role="alert">{assessment.error.message}</p>}
    </>}

    {stage === "results" && assessment.data && <>
      <div className={`troubleshooting-outcome troubleshooting-outcome--${assessment.data.outcome}`} role="status">
        <p className="eyebrow">Check complete</p>
        <h3>{assessment.data.headline}</h3>
        <p>{assessment.data.detail}</p>
      </div>

      <ul className="troubleshooting-checks" aria-label="Troubleshooting results">
        {assessment.data.checks.map(check => <li key={check.id} className={`troubleshooting-check troubleshooting-check--${check.status}`}>
          <span aria-hidden="true">{check.status === "passed" ? "✓" : check.status === "flagged" ? "!" : check.status === "unknown" ? "?" : "i"}</span>
          <div>
            <small>{statusLabels[check.status]}{check.certainty !== "none" ? ` · ${check.certainty}` : ""}</small>
            <strong>{check.label}</strong>
            <p>{check.detail}</p>
          </div>
        </li>)}
      </ul>

      {assessment.data.actions.length > 0 && <div className="troubleshooting-repairs">
        <h3>Available repairs</h3>
        {assessment.data.actions.map(action => <article key={action.id}>
          <div><strong>{action.label}</strong><p>{action.description}</p><small>{action.impact}</small></div>
          <Button disabled={!action.available || repair.isPending} onClick={() => setPendingAction(action)}>Review repair</Button>
          {action.blockers.map(blocker => <span className="warning" key={blocker}>{blocker}</span>)}
        </article>)}
      </div>}

      {repairResult && <p className="success" role="status">{repairResult}</p>}
      {repair.error && <p className="error" role="alert">{repair.error.message}</p>}

      <div className="troubleshooting-next">
        <h3>Next steps</h3>
        <ol>{assessment.data.next_steps.map(step => <li key={step}>{step}</li>)}</ol>
      </div>

      <details className="troubleshooting-sources">
        <summary>Factual sources used by this result</summary>
        <ul>{assessment.data.sources.map(source => <li key={source.id}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a><span>{source.publisher} · checked {source.checked_at}</span></li>)}</ul>
      </details>

      <div className="troubleshooting-actions">
        <Button className="button--secondary" disabled={assessment.isPending} onClick={() => runAssessment()}>{assessment.isPending ? "Checking again…" : "Run checks again"}</Button>
        <Button className="button--quiet" onClick={reset}>Choose another problem</Button>
      </div>
    </>}

    {pendingAction && <div className="troubleshooting-confirmation" role="dialog" aria-modal="true" aria-labelledby="repair-confirmation-heading">
      <div>
        <p className="eyebrow">Permission required</p>
        <h3 id="repair-confirmation-heading">Review “{pendingAction.label}”</h3>
        <p>{pendingAction.confirmation}</p>
        <dl>
          <div><dt>What changes</dt><dd>{pendingAction.description}</dd></div>
          <div><dt>Expected effect</dt><dd>{pendingAction.impact}</dd></div>
          <div><dt>Destructive?</dt><dd>No. Troubleshooting repairs cannot delete world data.</dd></div>
        </dl>
        <p className="muted-note">Nothing has changed yet. Blockstead will record the requested repair in Activity and run the checks again afterward.</p>
        <div className="troubleshooting-actions">
          <Button className="button--secondary" onClick={() => setPendingAction(null)}>Cancel</Button>
          <Button disabled={repair.isPending} onClick={() => repair.mutate(pendingAction)}>{repair.isPending ? "Applying…" : `Confirm ${pendingAction.label}`}</Button>
        </div>
      </div>
    </div>}
  </section>;
}
