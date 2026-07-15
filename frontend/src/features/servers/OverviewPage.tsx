import { PrerequisitesPanel } from "../extensions/PrerequisitesPanel";
import { useServerScope } from "./scope";

export function OverviewPage() {
  const scope = useServerScope();
  return <>
    <section className="metrics" aria-label="Server summary">
      <article><span>Server state</span><strong>{scope.state}</strong><small>{scope.running ? "Accepting commands" : "Not using host resources"}</small></article>
      <article><span>Minecraft</span><strong>{scope.profile.minecraft_version ?? "—"}</strong><small>{scope.profile.distribution}</small></article>
      <article><span>Process ID</span><strong>{scope.pid ?? "—"}</strong><small>{scope.pid ? "Managed by Blockstead" : "No active process"}</small></article>
      <article><span>Last exit</span><strong>{scope.exitCode ?? "—"}</strong><small>{scope.exitCode == null ? "No exit recorded" : scope.exitCode === 0 ? "Clean shutdown" : "Needs attention"}</small></article>
    </section>
    <PrerequisitesPanel profileId={scope.profile.id} />
  </>;
}
