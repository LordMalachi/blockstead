import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Profile } from "../../api/client";
import { Button } from "../../components/Button";

/** Matches what the API accepts, so a typo is answered here rather than by a 422. */
const VERSION = /^[0-9][0-9A-Za-z._-]{0,31}$/;

interface RecordedVersion { id: string; name: string; distribution: string; minecraft_version: string }

export function MinecraftVersionCard({ profile }: { profile: Profile }) {
  const cache = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState("");

  const save = useMutation({
    mutationFn: (minecraft_version: string) => api<RecordedVersion>(`/profiles/${profile.id}/minecraft-version`, {
      method: "PUT",
      body: JSON.stringify({ minecraft_version }),
    }),
    onSuccess: () => {
      setEditing(false);
      setDraft("");
      void cache.invalidateQueries({ queryKey: ["profiles"] });
    },
  });

  function submit() {
    const value = draft.trim();
    if (!VERSION.test(value)) {
      setProblem("Enter a Minecraft version such as 1.21.4.");
      return;
    }
    setProblem("");
    save.mutate(value);
  }

  return <section className="card" aria-labelledby="minecraft-version-heading">
    <div className="section-heading">
      <div><p className="eyebrow">This server</p><h2 id="minecraft-version-heading">Minecraft version</h2></div>
      <span>{profile.minecraft_version ?? "Not recorded"}</span>
    </div>
    {profile.minecraft_version
      ? <p className="muted-note">Blockstead matches mods, plugins, and Java against Minecraft {profile.minecraft_version}. Correct it if this server is actually running something else.</p>
      : <p className="warning" role="status">Blockstead could not tell which Minecraft version this server runs, so anything that has to match a version — installing mods or plugins, upgrade checks, and creating a modded copy — stays unavailable until it is recorded.</p>}
    {!editing && <div className="settings-actions">
      <Button className="button--secondary" onClick={() => { setEditing(true); setDraft(profile.minecraft_version ?? ""); setProblem(""); save.reset(); }}>
        {profile.minecraft_version ? "Change version" : "Record the version"}
      </Button>
    </div>}
    {editing && <>
      <label>Minecraft version number<input value={draft} placeholder="1.21.4" maxLength={32} onChange={event => { setDraft(event.target.value); setProblem(""); }} /></label>
      <p className="muted-note">It is printed in the server console at startup, and shown on the Minecraft launcher screen the world was made with.</p>
      {(problem || save.error) && <p className="error" role="alert">{problem || save.error?.message}</p>}
      <div className="settings-actions">
        <Button disabled={save.isPending} onClick={submit}>{save.isPending ? "Saving…" : "Save version"}</Button>
        <Button className="button--quiet" disabled={save.isPending} onClick={() => { setEditing(false); setProblem(""); save.reset(); }}>Cancel</Button>
      </div>
    </>}
  </section>;
}
