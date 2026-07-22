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
  keywords: string;
  page: string | null;
  action: string;
  href?: string;
}

interface RecoverySuggestion {
  title: string;
  description: string;
  href: string;
}

const topics: HelpTopic[] = [
  { title: "Get a server online", category: "Getting started", summary: "Create a supported server, copy in an existing folder, or start from a modpack; then review readiness, accept the EULA, and start safely.", keywords: "setup create import copy folder modpack mrpack eula java launcher readiness first server offline won't start", page: "overview", action: "Open server setup" },
  { title: "Help friends join", category: "Connecting", summary: "Find the local address, understand why a public address may be unavailable, and work through router, firewall, and provider checks.", keywords: "connect connection join address ip lan network port invite internet router firewall cgnat vpn public", page: "overview", action: "Open join details" },
  { title: "Start, stop, and use the console", category: "Everyday care", summary: "Follow live logs, use guided commands, restart cleanly, and understand why a server may refuse to start.", keywords: "start stop restart console log command crash failed running process", page: "console", action: "Open the console" },
  { title: "Manage players", category: "Everyday care", summary: "Maintain the allowlist, operators, and bans through validated actions instead of editing player files by hand.", keywords: "player whitelist allowlist operator op deop ban pardon access", page: "players", action: "Open player tools" },
  { title: "Protect, save, and restore a world", category: "Safety", summary: "Create verified backups, save a portable copy, choose retention and mirror rules, preview a restore, and preserve the world being replaced.", keywords: "backup save copy export download archive restore retention mirror world recover rollback drive", page: "backups", action: "Open Backup Center" },
  { title: "Set a weekly routine", category: "Automation", summary: "Schedule starts and maintenance, back up before stopping, add one-time work, and preview every step before it runs.", keywords: "schedule automation time day recurring maintenance shutdown power wake rtc event", page: "schedule", action: "Open scheduling" },
  { title: "Find and manage mods, plugins, and maps", category: "Extensions", summary: "Browse releases filtered for this server while friends play, then stop safely to install, upload, update, disable, remove, or configure your loadout.", keywords: "mod plugin extension modrinth curseforge hangar paper fabric jar version update squaremap", page: "mods", action: "Open Extension Workshop" },
  { title: "Change server settings", category: "Configuration", summary: "Use typed fields, validation, and an exact change preview. Blockstead saves a private recovery snapshot before writing the file.", keywords: "settings server properties motd difficulty player limit port configuration snapshot", page: "settings", action: "Open settings" },
  { title: "Understand activity, alerts, and support reports", category: "Support", summary: "Filter changes across every server, follow recovery links, choose which local alerts matter, and download a redacted report centered on one event.", keywords: "activity history notification alert accepted success failed outcome recovery report support logs mark seen", page: null, action: "Open Activity", href: "/activity" },
  { title: "Diagnose a problem", category: "Support", summary: "Check computer health, Java discovery, and recent errors, then save a diagnostic report that you can review before sharing.", keywords: "diagnose error failed crash cpu memory ram disk storage java report support doctor logs", page: null, action: "Open System" },
  { title: "Update Blockstead", category: "Software", summary: "Check whether a newer tested build is available, see whether this installation can update itself, and understand the player-safe update behavior.", keywords: "update upgrade newer version release install automatic manual current latest software blockstead", page: null, action: "Open updates", href: "/system#updates" },
  { title: "Reset the administrator password", category: "Recovery", summary: "Use a local terminal command on the Blockstead computer, with separate instructions for native Linux and Docker Compose installs.", keywords: "password forgot reset sign in login locked out administrator docker", page: null, action: "Open reset instructions", href: "#password-recovery" },
];

function recoverySuggestions(terms: string[]): RecoverySuggestion[] {
  const hasAny = (...words: string[]) => words.some(word => terms.includes(word));
  if (hasAny("crash", "crashed", "error", "failed", "failure", "won't", "wont", "start", "stopped")) return [
    { title: "Open Activity", description: "Find the failed event and its recovery link.", href: "/activity" },
    { title: "Open diagnostics", description: "Check Java, disk space, and recorded errors before sharing a report.", href: "/system" },
  ];
  if (hasAny("lag", "slow", "performance", "memory", "ram", "cpu", "disk", "storage")) return [
    { title: "Check system health", description: "Review the computer's CPU, memory, disk space, and recent errors.", href: "/system" },
    { title: "Open Activity", description: "See whether a backup, restart, or another recent change lines up with the problem.", href: "/activity" },
  ];
  return [
    { title: "Open Activity", description: "Find recent changes and any recovery link Blockstead recorded.", href: "/activity" },
    { title: "Open diagnostics", description: "Check the host and save a reviewable support report if needed.", href: "/system" },
  ];
}

export function HelpPage() {
  const [query, setQuery] = useState("");
  const [passwordOpen, setPasswordOpen] = useState(false);
  const { start } = useWalkthrough();
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state") });
  const activeProfile = profiles.data?.find(entry => entry.id === state.data?.profile_id);
  const profile = activeProfile ?? (profiles.data?.length === 1 ? profiles.data[0] : undefined);
  const normalized = query.trim().toLowerCase();
  const terms = normalized.split(/\s+/).filter(Boolean);
  const visible = topics.filter(topic => {
    const searchable = `${topic.title} ${topic.category} ${topic.summary} ${topic.keywords}`.toLowerCase();
    return terms.every(term => searchable.includes(term));
  });
  const suggestions = recoverySuggestions(terms);
  const topicLink = (topic: HelpTopic) => topic.href ?? (topic.page && profile ? `/servers/${profile.id}/${topic.page}` : topic.page ? "/servers" : "/system");

  return <>
    <section className="help-hero">
      <div>
        <p className="eyebrow">Guidance and recovery</p>
        <h1>How can we help?</h1>
        <p>Describe what you want to do, jump to the right workspace, or replay the guided tour. Opening help never changes your server.</p>
      </div>
      <div className="help-tour-card">
        <strong>New here?</strong>
        <span>Take a short visual tour of navigation, support tools, and Blockstead’s safety boundaries.</span>
        <Button onClick={start}>Start guided tour</Button>
      </div>
      <label className="help-search">
        <span>Find a task</span>
        <input aria-label="Search help" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Join, backups, whitelist, Java, crash…" />
      </label>
    </section>

    <section className="help-topics" aria-labelledby="help-topics-heading">
      <div className="section-heading"><div><p className="eyebrow">Task shortcuts</p><h2 id="help-topics-heading">Start with what you want to do</h2></div><span aria-live="polite">{visible.length} result{visible.length === 1 ? "" : "s"}</span></div>
      {visible.length > 0 ? <div className="help-topic-grid">{visible.map(topic => <article className="help-topic" key={topic.title}>
        <span>{topic.category}</span>
        <h3>{topic.title}</h3>
        <p>{topic.summary}</p>
        <Link to={topicLink(topic)} onClick={topic.href === "#password-recovery" ? () => setPasswordOpen(true) : undefined}>{topic.page && !profile ? "Choose a server" : topic.action}<span aria-hidden="true"> →</span></Link>
      </article>)}</div> : <div className="help-no-results">
        <h3>No task shortcut matched “{query.trim()}”</h3>
        <p>Try a simpler word such as “players,” “join,” “backup,” or “crash.” If something is wrong, these are safe places to start.</p>
        <div className="help-recovery-suggestions" aria-label="Recovery suggestions">
          {suggestions.map(suggestion => <Link key={suggestion.href} className="help-recovery-suggestion" to={suggestion.href}>
            <strong>{suggestion.title}</strong><span>{suggestion.description}</span>
          </Link>)}
        </div>
        <div className="help-no-results__actions">
          <Button className="button--secondary" onClick={() => setQuery("")}>Clear search</Button>
        </div>
      </div>}
    </section>

    <div className="help-columns">
      <section className="card help-answers">
        <p className="eyebrow">Quick answers</p>
        <h2>Common questions</h2>
        <details><summary>Does Blockstead expose my server to the internet?</summary><p>No. Blockstead does not open firewall rules or configure your router. Dashboard and Minecraft network access remain choices you make on this computer and network.</p></details>
        <details id="connection-troubleshooting"><summary>Why can’t Blockstead show a public Minecraft address?</summary><p>Blockstead asks a public-IP service for the network’s current public IP, but it does not use a saved address or assume that the dashboard address is where Minecraft is reachable. It cannot reliably learn the router’s outside port or test every provider and firewall from inside your network, so it deliberately withholds a public Minecraft address until you confirm that mapping.</p><p>First, retry the check without a VPN or proxy. Then make sure Minecraft is listening on the local network, permit its port through the host firewall, and forward the router’s outside port to this computer’s local address and Minecraft port. Ask a friend on another network to test. If forwarding still fails, look for double NAT or carrier-grade NAT from your internet provider; a public IP in the router may not be enough.</p><p>The connection panel can safely retry IP discovery and, when the server is bound only to this computer, can clear that loopback bind after you explicitly choose it. It never changes your router or firewall automatically.</p></details>
        <details><summary>What happens when my browser closes?</summary><p>The installed Blockstead service and Minecraft process keep running. Reopen the Blockstead app icon or dashboard later to reconnect.</p></details>
        <details><summary>Why must some changes wait until the server stops?</summary><p>Mods, restores, and some configuration files are locked while Minecraft is active so a partial write cannot damage the running server or world.</p></details>
        <details><summary>Can I look for mods or plugins while people are playing?</summary><p>Yes. You can browse catalogs and compare releases listed for this server at any time. Blockstead waits until Minecraft is fully stopped before it installs, updates, uploads, enables, disables, or removes a jar.</p></details>
        <details><summary>What is the difference between a backup and Save a copy?</summary><p>Back up now creates Blockstead’s private, verified restore point. Save a copy exports an already completed archive to your browser or a folder you choose, which is handy for another drive or a little extra peace of mind.</p></details>
        <details><summary>Will backup cleanup remove the only good copy?</summary><p>No. Retention rules can remove older primary archives, but Blockstead always keeps the newest completed one. Optional mirrored copies on another drive are not pruned by those primary rules.</p></details>
        <details><summary>What do the question-mark buttons do?</summary><p>Hover over one, focus it with the keyboard, or tap it for a short explanation of the nearby choice. Tooltips only explain; they never apply a change.</p></details>
        <details><summary>What does “accepted” mean in Activity?</summary><p>Accepted means Blockstead received and safely handed off the request. Success means the tracked operation finished. For commands handled inside Minecraft, check the console or later activity when you need to confirm the game completed it.</p></details>
        <details><summary>What is in an event support report?</summary><p>It combines the selected event with redacted system context and application logs from roughly fifteen minutes around it. It may still contain server and player names, so review it before sharing. Blockstead never uploads it automatically.</p></details>
        <details><summary>Why can an alert remain after I mark it seen?</summary><p>Mark seen clears unread event alerts. An ongoing condition such as low disk space can remain visible until the condition is fixed, because it still needs attention.</p></details>
        <details><summary>Where does Blockstead keep recovery copies?</summary><p>Backup archives and settings snapshots stay in Blockstead’s private data. Preserved worlds and mod-configuration backups stay inside the selected server folder. Restoring settings or configuration backups currently requires access to the host computer.</p></details>
      </section>

      <section className="card help-recovery">
        <p className="eyebrow">When something is wrong</p>
        <h2>Recovery shortcuts</h2>
        <ol>
          <li><strong>Start with Overview.</strong><span>Its Needs attention list links to the relevant workspace; Server readiness names anything still blocking Start.</span></li>
          <li><strong>Open Activity.</strong><span>Find the failed event, follow its recovery link, and download the focused support report if you need to send context.</span></li>
          <li><strong>Open System.</strong><span>Check disk space, Java, and recent recorded errors; its broader report covers the installation rather than one event.</span></li>
          <li><strong>For a native Linux install, run the local doctor.</strong><code>blockstead doctor</code></li>
          <li><strong>Review before sharing.</strong><span>Reports can include server and player names. Nothing is uploaded; share one only when you choose.</span></li>
        </ol>
        <div className="row-actions"><Link className="button button--secondary" to="/activity">Open Activity</Link><Link className="button button--quiet" to="/system">Open diagnostics</Link></div>
        <details className="help-password" id="password-recovery" open={passwordOpen} onToggle={event => setPasswordOpen(event.currentTarget.open)}><summary>Forgot the administrator password?</summary><p>For a native Linux install, run:</p><code>sudo blockstead reset-password</code><p>Using Docker Compose? Run this from the Blockstead folder:</p><code>docker compose exec blockstead blockstead reset-password</code><small>Both commands require control of the host computer and sign out existing dashboard sessions.</small></details>
      </section>
    </div>
  </>;
}
