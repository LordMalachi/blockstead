import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type PrerequisitesView } from "../../api/client";
import { Button } from "../../components/Button";

export function PrerequisitesPanel({ profileId }: { profileId: string }) {
  const client = useQueryClient();
  const prerequisites = useQuery({ queryKey: ["prerequisites", profileId], queryFn: () => api<PrerequisitesView>(`/profiles/${profileId}/prerequisites`) });
  const accept = useMutation({
    mutationFn: () => api(`/profiles/${profileId}/eula`, { method: "POST", body: JSON.stringify({ accept: true }) }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["prerequisites", profileId] }); },
  });
  const view = prerequisites.data;
  if (!view) return <section className="card" id="readiness"><p className="empty-note">Checking server requirements…</p></section>;
  const ready = view.eula_accepted && view.java_satisfied && view.launch_files_ready;
  return <section className="card" id="readiness"><div className="section-heading"><div><p className="eyebrow">Before first launch</p><h2>Server readiness</h2></div><span className={ready ? "state-label state-label--ok" : "state-label state-label--warning"}>{ready ? "Ready" : "Action needed"}</span></div><div className="readiness-grid"><article><strong>{view.launch_files_ready ? "Launcher found" : "Launcher needs attention"}</strong><small>{view.launch_problem ?? `${view.label} ${view.minecraft_version ?? "version unknown"}`}</small></article><article><strong>{view.java_satisfied ? `Java ${view.selected_java?.major ?? "ready"}` : `Java ${view.required_java_major ?? "runtime"} needed`}</strong><small>{view.selected_java ? view.selected_java.path : "Install a compatible Java runtime on the Blockstead host."}</small></article><article><strong>{view.eula_accepted ? "EULA accepted" : "EULA not accepted"}</strong><small>{view.eula_accepted ? "This profile may pass the EULA launch gate." : "Review the Minecraft EULA, then explicitly accept it for this profile."}</small>{!view.eula_accepted && <Button className="button--small" disabled={accept.isPending} onClick={() => accept.mutate()}>{accept.isPending ? "Recording…" : "Accept Minecraft EULA"}</Button>}</article></div>{accept.error && <p className="error" role="alert">{accept.error.message}</p>}</section>;
}
