import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  api,
  type LoaderMigrationResult,
  type LoaderMigrationReview,
  type Profile,
} from "../../api/client";
import { Button } from "../../components/Button";
import { FieldNotice, useFieldErrors } from "../../components/FieldError";
import { formatBytes } from "../../lib/format";
import { describeServerDirectoryName, normalizeServerDirectoryName } from "../../lib/server-directory";

const targets = [
  ["paper", "Paper", "Server plugins; players use normal Minecraft."],
  ["fabric", "Fabric", "Lightweight mod loader with a large server-mod ecosystem."],
  ["forge", "Forge", "Long-running mod loader used by many established mods."],
  ["neoforge", "NeoForge", "Modern Forge-derived loader for newer mod releases."],
  ["quilt", "Quilt", "Fabric-derived loader with support for many Fabric mods."],
] as const;

function childPath(parent: string, child: string) {
  const separator = parent.includes("\\") ? "\\" : "/";
  return `${parent.replace(/[\\/]+$/, "")}${separator}${child}`;
}

export function LoaderMigrationPanel({ profileId }: { profileId: string }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const source = profiles.data?.find(profile => profile.id === profileId);
  const [target, setTarget] = useState<(typeof targets)[number][0]>("paper");
  const suggestedName = useMemo(() => `${source?.name ?? "Server"} · ${targets.find(item => item[0] === target)?.[1]}`, [source?.name, target]);
  const [name, setName] = useState("");
  const [directory, setDirectory] = useState("");
  const [acknowledge, setAcknowledge] = useState(false);
  const fieldErrors = useFieldErrors();

  const review = useMutation({
    mutationFn: () => api<LoaderMigrationReview>(`/profiles/${profileId}/loader-migration/review`, {
      method: "POST",
      body: JSON.stringify({ target_distribution: target }),
    }),
    onMutate: () => setAcknowledge(false),
  });
  const plan = review.data?.target_distribution === target ? review.data : null;
  const chosenDirectory = normalizeServerDirectoryName(directory, normalizeServerDirectoryName(suggestedName, "modded-server"));
  const destinationDirectory = plan ? childPath(plan.destination_root, chosenDirectory) : "";
  const apply = useMutation({
    mutationFn: () => api<LoaderMigrationResult>(`/profiles/${profileId}/loader-migration/apply`, {
      method: "POST",
      body: JSON.stringify({
        target_distribution: target,
        review_id: plan?.review_id,
        backup_id: plan?.protection.backup_id,
        loader_version: plan?.loader_version,
        name: name.trim() || suggestedName,
        directory_name: chosenDirectory,
        acknowledge_modded_world: acknowledge,
      }),
    }),
    onSuccess: result => {
      fieldErrors.clear();
      sessionStorage.setItem(`blockstead_migration_${result.id}`, JSON.stringify(result));
      void client.invalidateQueries({ queryKey: ["profiles"] });
      void navigate(result.next_route);
    },
    onError: error => fieldErrors.setFromError(error),
  });

  function changeTarget(value: typeof target) {
    setTarget(value);
    setName("");
    setDirectory("");
    fieldErrors.clear();
    review.reset();
    apply.reset();
  }

  // Live-check the folder name as the owner types, so an invalid value shows its
  // suggestion immediately instead of only after submit or on blur.
  function changeDirectory(value: string) {
    setDirectory(value);
    fieldErrors.setField("directory_name", value.trim() ? describeServerDirectoryName(value, normalizeServerDirectoryName(suggestedName, "modded-server")) : null);
  }
  const nameError = fieldErrors.get("name");
  const directoryError = fieldErrors.get("directory_name");

  return <section className="maintenance-migration" aria-labelledby="migration-heading">
    <div>
      <p className="eyebrow">Existing world</p>
      <h3 id="migration-heading">Create a modded copy</h3>
      <p>Keep this server untouched while Blockstead creates a separate loader profile and copies its world data. Paper uses plugins; Fabric, Forge, NeoForge, and Quilt use mods.</p>
    </div>
    <div className="migration-targets" role="radiogroup" aria-label="New server loader">
      {targets.map(([value, label, detail]) => <label key={value} className={target === value ? "is-selected" : ""}>
        <input type="radio" name="migration-target" value={value} checked={target === value} onChange={() => changeTarget(value)} />
        <strong>{label}</strong>
        <span>{detail}</span>
      </label>)}
    </div>
    <div className="maintenance-actions">
      <Button disabled={review.isPending} onClick={() => review.mutate()}>
        {review.isPending ? "Checking loader and world…" : "Review modded copy"}
      </Button>
    </div>
    {review.error && <p className="error" role="alert">{review.error.message}</p>}
    {plan && <div className="migration-review">
      <div className="migration-review__summary">
        <strong>{plan.target_distribution} {plan.minecraft_version}{plan.loader_version ? ` · loader ${plan.loader_version}` : ""}</strong>
        <span>{plan.world_size_bytes == null ? "World size unavailable" : `${formatBytes(plan.world_size_bytes)} across ${plan.worlds.join(", ")}`}</span>
        <span>{plan.java_ready ? `Java ${plan.required_java_major ?? "ready"} available` : `Java ${plan.required_java_major} needed`}</span>
        <span className={plan.protection.verified ? "success" : "warning"}>{plan.protection.detail}</span>
      </div>
      <div className="migration-review__locations" aria-label="World copy locations">
        <h4>Where the world data goes</h4>
        <dl>
          <div><dt>Source server</dt><dd><code>{plan.source_directory}</code><small>This folder stays in place and is not changed.</small></dd></div>
          <div><dt>New server</dt><dd><code>{destinationDirectory}</code><small>A separate folder created under Blockstead’s managed server root.</small></dd></div>
        </dl>
        {plan.world_copy_operations.length > 0 && <ul>{plan.world_copy_operations.map(operation => <li key={`${operation.source_path}:${operation.destination_relative_path}`}>
          <code>{operation.source_path}</code><span aria-hidden="true"> → </span><code>{childPath(destinationDirectory, operation.destination_relative_path)}</code>
          <small>{operation.detail}</small>
        </li>)}</ul>}
        <p className="muted-note">Only the reviewed world paths above are copied. Loader files, mods, plugins, and source configuration are not moved.</p>
      </div>
      {plan.blockers.length > 0 && <div className="maintenance-blocked" role="alert">
        <strong>Resolve before creating the copy</strong>
        <ul>{plan.blockers.map(blocker => <li key={blocker}>{blocker}</li>)}</ul>
        {plan.worlds.length === 0 && <p>Start the source server once and let it finish creating its world, then stop it and create a verified backup. Blockstead will copy the world into a new server and leave the source untouched.</p>}
        {!plan.protection.verified && <Link className="button button--secondary button--small" to={`/servers/${profileId}/backups`}>Create a backup</Link>}
      </div>}
      {plan.extensions.length > 0 && <div>
        <h4>Extension rebuild checklist</h4>
        <ul className="migration-extension-list">{plan.extensions.map(extension => <li key={extension.file_name}>
          <strong>{extension.name}{extension.version ? ` · ${extension.version}` : ""}</strong>
          <span>{extension.classification.replaceAll("_", " ")}</span>
          <small>{extension.detail}</small>
        </li>)}</ul>
      </div>}
      {plan.ready && <div className="migration-create">
        <label>New profile name<input value={name} placeholder={suggestedName} maxLength={80} onChange={event => setName(event.target.value)} {...fieldErrors.controlProps("name")} /></label>
        {nameError && <FieldNotice id={fieldErrors.noticeId("name")} error={nameError} onUseSuggestion={value => setName(value)} />}
        <label>New server folder<input value={directory} placeholder={normalizeServerDirectoryName(suggestedName, "modded-server")} pattern="[a-z0-9][a-z0-9_-]*" maxLength={64} onChange={event => changeDirectory(event.target.value)} onBlur={() => { if (directory.trim()) changeDirectory(chosenDirectory); }} {...fieldErrors.controlProps("directory_name")} /></label>
        {directoryError && <FieldNotice id={fieldErrors.noticeId("directory_name")} error={directoryError} onUseSuggestion={value => changeDirectory(value)} />}
        <small>The complete destination will be <code>{destinationDirectory}</code>.</small>
        {directory.trim() && directory.trim() !== chosenDirectory && <small className="muted-note">The folder name will be saved as <code>{chosenDirectory}</code> so it works on every supported host.</small>}
        {plan.modded_world_warning && <label className="maintenance-booking-toggle">
          <input type="checkbox" checked={acknowledge} onChange={event => setAcknowledge(event.target.checked)} />
          <span>I understand unavailable source mods may leave custom world content unreadable in the new loader.</span>
        </label>}
        <Button disabled={apply.isPending || (plan.modded_world_warning && !acknowledge)} onClick={() => apply.mutate()}>
          {apply.isPending ? "Provisioning and copying…" : `Create ${targets.find(item => item[0] === target)?.[1]} copy`}
        </Button>
      </div>}
      {apply.error && <p className="error" role="alert">{apply.error.message}</p>}
    </div>}
  </section>;
}
