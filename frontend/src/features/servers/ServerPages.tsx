import { ExtensionsPanel } from "../extensions/ExtensionsPanel";
import { FilesPanel } from "../files/FilesPanel";
import { PlayersPanel } from "../players/PlayersPanel";
import { SchedulePanel } from "../schedule/SchedulePanel";
import { SettingsPanel } from "../settings/SettingsPanel";
import { useServerScope } from "./scope";

export function PlayersPage() {
  const scope = useServerScope();
  return <PlayersPanel profileId={scope.profile.id} running={scope.running} />;
}

export function ModsPage() {
  const scope = useServerScope();
  return <ExtensionsPanel profileId={scope.profile.id} stopped={scope.stopped} />;
}

export function SchedulePage() {
  const scope = useServerScope();
  return <SchedulePanel profileId={scope.profile.id} />;
}

export function BackupsPage() {
  const scope = useServerScope();
  return <BackupsPanel profileId={scope.profile.id} running={scope.running} serverState={scope.state} />;
}

export function SettingsPage() {
  const scope = useServerScope();
  return <SettingsPanel profileId={scope.profile.id} running={scope.running} />;
}

export function FilesPage() {
  const scope = useServerScope();
  return <FilesPanel profileId={scope.profile.id} distribution={scope.profile.distribution} stopped={scope.stopped} />;
}
import { BackupsPanel } from "../backups/BackupsPanel";
