import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { SystemPanel } from "./SystemPanel";
import { UpdatePanel } from "./UpdatePanel";

export function SystemPage() {
  return <>
    <section className="page-head"><div><p className="eyebrow">Blockstead host</p><h1>System</h1><p>Health for the computer running Blockstead. Each server keeps its own schedule and settings in its workspace.</p></div></section>
    <SystemPanel />
    <UpdatePanel />
    <DiagnosticsPanel />
  </>;
}
