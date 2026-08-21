import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Profile, type SavedSetup, type SavedSetupSwitchReview, type SavedSetupVariantReview } from "../../api/client";
import { Button } from "../../components/Button";
import { normalizeServerDirectoryName } from "../../lib/server-directory";

const distributions = ["vanilla", "paper", "fabric", "forge", "quilt", "neoforge"];

export function SavedSetupsPanel({ profiles }: { profiles: Profile[] }) {
  const client = useQueryClient();
  const [setupName, setSetupName] = useState("");
  const [sourceProfileId, setSourceProfileId] = useState(profiles[0]?.id ?? "");
  const [variantName, setVariantName] = useState("");
  const [directoryName, setDirectoryName] = useState("");
  const [distribution, setDistribution] = useState("vanilla");
  const [review, setReview] = useState<SavedSetupVariantReview | null>(null);
  const [switchReview, setSwitchReview] = useState<SavedSetupSwitchReview | null>(null);
  const [acknowledge, setAcknowledge] = useState(false);
  const [notice, setNotice] = useState("");
  const setups = useQuery({ queryKey: ["saved-setups"], queryFn: () => api<SavedSetup[]>("/saved-setups") });
  const setupList = Array.isArray(setups.data) ? setups.data : [];
  const createSetup = useMutation({
    mutationFn: () => api<unknown>("/saved-setups", { method: "POST", body: JSON.stringify({ name: setupName, profile_id: sourceProfileId }) }),
    onSuccess: async () => { setSetupName(""); setNotice("Saved setup created. Review a protected variant below."); await client.invalidateQueries({ queryKey: ["saved-setups"] }); },
    onError: error => setNotice(error.message),
  });
  const createReview = useMutation({
    mutationFn: (setupId: string) => api<SavedSetupVariantReview>(`/saved-setups/${setupId}/variants/review`, { method: "POST", body: JSON.stringify({ source_profile_id: sourceProfileId, name: variantName, directory_name: normalizeServerDirectoryName(directoryName, "creative-snapshot"), target_distribution: distribution }) }),
    onSuccess: data => { setReview(data); setNotice(""); },
    onError: error => setNotice(error.message),
  });
  const createVariant = useMutation({
    mutationFn: (setupId: string) => api<unknown>(`/saved-setups/${setupId}/variants`, { method: "POST", body: JSON.stringify({ source_profile_id: sourceProfileId, name: variantName, directory_name: normalizeServerDirectoryName(directoryName, "creative-snapshot"), target_distribution: distribution, review_id: review?.review_id, backup_id: review?.protection.backup_id, acknowledge_modded_world: acknowledge }) }),
    onSuccess: async () => { setReview(null); setNotice("Protected setup variant created; the source profile remains unchanged."); await client.invalidateQueries({ queryKey: ["saved-setups"] }); await client.invalidateQueries({ queryKey: ["profiles"] }); },
    onError: error => setNotice(error.message),
  });
  const reviewSwitch = useMutation({
    mutationFn: (targetProfileId: string) => api<SavedSetupSwitchReview>(`/saved-setups/${setupList.find(setup => setup.variants.some(variant => variant.profile_id === targetProfileId))?.id ?? ""}/switch/review`, { method: "POST", body: JSON.stringify({ target_profile_id: targetProfileId }) }),
    onSuccess: data => { setSwitchReview(data); setNotice(""); },
    onError: error => setNotice(error.message),
  });
  const activate = useMutation({
    mutationFn: () => api<unknown>(`/saved-setups/${switchReview?.setup_id}/switch`, { method: "POST", body: JSON.stringify({ target_profile_id: switchReview?.target_profile_id, review_id: switchReview?.review_id, backup_id: switchReview?.current_backup_id, confirm: true }) }),
    onSuccess: async () => { setSwitchReview(null); setNotice("Saved setup activated. The server state is updating now."); await client.invalidateQueries(); },
    onError: error => setNotice(error.message),
  });

  function reviewVariant(event: FormEvent, setupId: string) {
    event.preventDefault();
    setNotice("");
    createReview.mutate(setupId);
  }

  return <section className="card" id="saved-setups">
    <div className="section-heading"><div><p className="eyebrow">Protected variants</p><h2>Saved Setups</h2></div><span>{setupList.length} group{setupList.length === 1 ? "" : "s"}</span></div>
    <p>Each variant is a separate Blockstead profile with its own world copy, port, launcher, backups, and logs. Switching always reviews protection and downtime first.</p>
    {notice && <p className="error" role="alert">{notice}</p>}
    <form className="inline-form" onSubmit={event => { event.preventDefault(); createSetup.mutate(); }}>
      <label>New setup group<input value={setupName} onChange={event => setSetupName(event.target.value)} placeholder="Weekend worlds" required maxLength={80} /></label>
      <label>Source profile<select value={sourceProfileId} onChange={event => setSourceProfileId(event.target.value)}>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
      <Button disabled={createSetup.isPending || !sourceProfileId}>{createSetup.isPending ? "Creating…" : "Create setup"}</Button>
    </form>
    {setupList.map(setup => <article className="card" key={setup.id}>
      <div className="section-heading"><div><h3>{setup.name}</h3><small>Variants diverge independently; source profiles are never parked in place.</small></div><span>{setup.variants.length} variant{setup.variants.length === 1 ? "" : "s"}</span></div>
      <ul className="care-list">{setup.variants.map(variant => <li key={variant.id}><div><strong>{variant.name}</strong><small>{variant.distribution} {variant.minecraft_version ?? ""} · {variant.active ? "active" : "stopped"}</small><small>Protection: {variant.protection_status === "verified" ? "verified" : "source enrollment or backup unavailable"}</small></div><Button className="button--secondary button--small" disabled={variant.active || reviewSwitch.isPending} onClick={() => reviewSwitch.mutate(variant.profile_id)}>Review switch</Button></li>)}</ul>
      <form className="inline-form" onSubmit={event => reviewVariant(event, setup.id)}>
        <label>Variant name<input value={variantName} onChange={event => setVariantName(event.target.value)} placeholder="Creative snapshot" required maxLength={80} /></label>
        <label>Folder name<input value={directoryName} onChange={event => setDirectoryName(event.target.value)} onBlur={() => setDirectoryName(current => normalizeServerDirectoryName(current, "creative-snapshot"))} placeholder="creative-snapshot" required pattern="[a-z0-9][a-z0-9_-]*" /></label>
        <label>Target loader<select value={distribution} onChange={event => setDistribution(event.target.value)}>{distributions.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <label>Copy from<select value={sourceProfileId} onChange={event => setSourceProfileId(event.target.value)}>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
        <Button disabled={createReview.isPending}>{createReview.isPending ? "Reviewing…" : "Review protected copy"}</Button>
      </form>
      {review?.setup_id === setup.id && <div className="warning" role="region" aria-label="Saved setup variant review"><strong>{review.ready ? "Ready for protected copy" : "Review needs attention"}</strong><span>World copy: {review.world_copy_operations.length} operation{review.world_copy_operations.length === 1 ? "" : "s"}. Java: {review.java_ready ? "ready" : "not ready"}. Source backup: {review.protection.detail}</span>{review.blockers.length > 0 && <ul>{review.blockers.map(blocker => <li key={blocker}>{blocker}</li>)}</ul>}{review.modded_world_warning && <label><input type="checkbox" checked={acknowledge} onChange={event => setAcknowledge(event.target.checked)} /> I understand loader-specific world content may need review.</label>}<Button disabled={!review.ready || !review.protection.backup_id || (review.modded_world_warning && !acknowledge) || createVariant.isPending} onClick={() => createVariant.mutate(setup.id)}>{createVariant.isPending ? "Copying safely…" : "Create protected variant"}</Button></div>}
    </article>)}
    {switchReview && <div className="troubleshooting-confirmation" role="dialog" aria-modal="true" aria-labelledby="saved-switch-heading"><div><p className="eyebrow">Activation confirmation</p><h2 id="saved-switch-heading">Switch to {switchReview.target_name}?</h2><p>Blockstead will stop the current profile safely, then start this target. Expected downtime: {switchReview.downtime_expected ? "yes" : "none"}.</p><dl><div><dt>Port</dt><dd>{switchReview.target_port}</dd></div><div><dt>Current backup</dt><dd>{switchReview.current_backup_verified ? "Verified backup selected" : "No verified running-profile backup"}</dd></div><div><dt>EULA</dt><dd>{switchReview.eula_ready ? "Ready" : "Needs acceptance"}</dd></div><div><dt>Java</dt><dd>{switchReview.java_ready ? "Ready" : "Needs attention"}</dd></div><div><dt>Launch plan</dt><dd>{switchReview.launch_ready ? "Ready" : switchReview.blockers.join(" ")}</dd></div></dl><Button className="button--secondary" onClick={() => setSwitchReview(null)}>Cancel</Button><Button className="button--danger" disabled={!switchReview.ready || activate.isPending} onClick={() => activate.mutate()}>{activate.isPending ? "Switching…" : "Confirm switch"}</Button></div></div>}
  </section>;
}
