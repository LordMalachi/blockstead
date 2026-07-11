import { useQuery } from "@tanstack/react-query";
import { api, type SettingEntry, type SettingsView } from "../../api/client";

function shown(entry: SettingEntry): string {
  if (entry.value === null) return "—";
  if (entry.type === "boolean") return entry.value ? "On" : "Off";
  return String(entry.value);
}

export function SettingsPanel({ profileId }: { profileId: string }) {
  const settings = useQuery({ queryKey: ["settings", profileId], queryFn: () => api<SettingsView>(`/profiles/${profileId}/settings`) });
  const view = settings.data;
  return <section className="card" id="settings"><div className="section-heading"><div><p className="eyebrow">server.properties</p><h2>Server settings</h2></div><span>Read-only</span></div>{!view ? <p className="empty-note">Loading settings…</p> : !view.present ? <p className="empty-note">No readable server.properties file was found in this profile folder.</p> : <><table className="settings-table"><thead><tr><th scope="col">Setting</th><th scope="col">Value</th><th scope="col">Key</th></tr></thead><tbody>{view.settings.map(entry => <tr key={entry.key}><td>{entry.label}</td><td><strong>{shown(entry)}</strong></td><td><code>{entry.key}</code></td></tr>)}</tbody></table>{view.other_keys.length > 0 && <p className="muted-note">Also present but not typed yet: {view.other_keys.join(", ")}.</p>}</>}<small className="muted-note">Blockstead shows these values without modifying the file. Guided editing with an automatic backup arrives in a later milestone.</small></section>;
}
