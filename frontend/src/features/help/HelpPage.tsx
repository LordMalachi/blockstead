import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type ProcessState, type Profile } from "../../api/client";
import { Button } from "../../components/Button";
import { useWalkthrough } from "./WalkthroughContext";

interface HelpTopic {
  title: string;
  category: string;
  summary: string;
  page: string | null;
  action: string;
}

const topics: HelpTopic[] = [
  { title: "Get a server online", category: "Getting started", summary: "Create a supported server or copy in an existing folder, review Java and launcher requirements, accept the EULA, and start safely.", page: "overview", action: "Open server setup" },
  { title: "Start, stop, and use the console", category: "Everyday care", summary: "Follow live logs, use guided commands, restart cleanly, and understand why a server may refuse to start.", page: "console", action: "Open the console" },
  { title: "Manage players", category: "Everyday care", summary: "Maintain the allowlist, operators, and bans through validated actions instead of editing player files by hand.", page: "players", action: "Open player tools" },
  { title: "Protect and restore a world", category: "Safety", summary: "Create verified backups, choose retention limits, preview a restore, and preserve the world being replaced.", page: "backups", action: "Open Backup Center" },
  { title: "Set a weekly routine", category: "Automation", summary: "Schedule starts and maintenance, back up before stopping, add one-time work, and preview every step before it runs.", page: "schedule", action: "Open scheduling" },
  { title: "Install mods, plugins, and a shared map", category: "Extensions", summary: "Search compatible releases across connected catalogs, install verified files, manage your active loadout, and tune generated configuration safely.", page: "mods", action: "Open mods and plugins" },
  { title: "Change server settings", category: "Configuration", summary: "Use typed fields and a change preview, then rely on automatic recovery snapshots if a setting needs to be reversed.", page: "settings", action: "Open settings" },
  { title: "Diagnose a problem", category: "Support", summary: "Check computer health, Java discovery, recent errors, and save a redacted diagnostic report to share when asking for help.", page: null, action: "Open System" },
];

export function HelpPage() {
  const [query, setQuery] = useState("");
  const { start } = useWalkthrough();
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state") });
  const profile = profiles.data?.find(entry => entry.id === state.data?.profile_id);
  const normalized = query.trim().toLowerCase();
  const visible = topics.filter(topic => !normalized || `${topic.title} ${topic.category} ${topic.summary}`.toLowerCase().includes(normalized));
  const topicLink = (topic: HelpTopic) => topic.page && profile ? `/servers/${profile.id}/${topic.page}` : topic.page ? "/servers" : "/system";

  return <>
    <section className="help-hero">
      <div>
        <p className="eyebrow">Guidance and recovery</p>
        <h1>How can we help?</h1>
        <p>Find the right Blockstead workspace, understand a technical choice, or replay the guided tour. These guides never change your server by themselves.</p>
      </div>
      <div className="help-tour-card">
        <strong>New here?</strong>
        <span>Take a two-minute tour of the main workspaces and Blockstead’s safety boundaries.</span>
        <Button onClick={start}>Start guided tour</Button>
      </div>
      <label className="help-search">
        <span>Search help</span>
        <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Backups, players, Java, schedules…" />
      </label>
    </section>

    <section className="help-topics" aria-labelledby="help-topics-heading">
      <div className="section-heading"><div><p className="eyebrow">Task guides</p><h2 id="help-topics-heading">Choose what you want to do</h2></div><span>{visible.length} guide{visible.length === 1 ? "" : "s"}</span></div>
      {visible.length > 0 ? <div className="help-topic-grid">{visible.map(topic => <article className="help-topic" key={topic.title}>
        <span>{topic.category}</span>
        <h3>{topic.title}</h3>
        <p>{topic.summary}</p>
        <Link to={topicLink(topic)}>{topic.page && !profile ? "Choose a server" : topic.action}<span aria-hidden="true"> →</span></Link>
      </article>)}</div> : <div className="help-no-results">
        <h3>No guide matched “{query.trim()}”</h3>
        <p>Try a shorter task or open System to review recent errors and download a diagnostic report.</p>
        <Link className="button button--secondary" to="/system">Open System</Link>
      </div>}
    </section>

    <div className="help-columns">
      <section className="card help-answers">
        <p className="eyebrow">Quick answers</p>
        <h2>Common questions</h2>
        <details><summary>Does Blockstead expose my server to the internet?</summary><p>No. Blockstead does not open firewall rules or configure your router. Dashboard and Minecraft network access remain choices you make on this computer and network.</p></details>
        <details><summary>What happens when my browser closes?</summary><p>The installed Blockstead service and Minecraft process keep running. Reopen the Blockstead app icon or dashboard later to reconnect.</p></details>
        <details><summary>Why must some changes wait until the server stops?</summary><p>Mods, restores, and some configuration files are locked while Minecraft is active so a partial write cannot damage the running server or world.</p></details>
        <details><summary>Where does Blockstead keep recovery copies?</summary><p>Settings snapshots, backup archives, and preserved restore folders stay in Blockstead’s private data or the selected managed server directory. The relevant page names each recovery copy.</p></details>
      </section>

      <section className="card help-recovery">
        <p className="eyebrow">When something is wrong</p>
        <h2>Recovery shortcuts</h2>
        <ol>
          <li><strong>Read the warning.</strong><span>Overview and Server readiness link to the workspace that can resolve it.</span></li>
          <li><strong>Open System.</strong><span>Check disk space, Java, and recent recorded errors.</span></li>
          <li><strong>Run the local doctor.</strong><code>blockstead doctor</code></li>
          <li><strong>Save a diagnostic report.</strong><span>Nothing is uploaded; attach it only when you choose to ask for help.</span></li>
        </ol>
        <Link className="button button--secondary" to="/system">Open diagnostics</Link>
        <details className="help-password"><summary>Forgot the administrator password?</summary><p>On the Linux computer, run:</p><code>sudo blockstead reset-password</code><small>This signs out existing dashboard sessions.</small></details>
      </section>
    </div>
  </>;
}
