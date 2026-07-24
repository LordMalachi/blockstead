import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type NotificationPreferences, type PlayerAction, type RosterEntry, type RosterView } from "../../api/client";
import { Button } from "../../components/Button";

const ACTIONS: { value: PlayerAction; label: string }[] = [
  { value: "whitelist_add", label: "Add to allowlist" },
  { value: "whitelist_remove", label: "Remove from allowlist" },
  { value: "op", label: "Make operator" },
  { value: "deop", label: "Remove operator" },
  { value: "ban", label: "Ban" },
  { value: "pardon", label: "Unban" },
  { value: "kick", label: "Kick" },
];

const FILTERS = [
  { value: "all", label: "All" },
  { value: "online", label: "Online" },
  { value: "allowlisted", label: "Allowlisted" },
  { value: "operators", label: "Operators" },
  { value: "banned", label: "Banned" },
] as const;
type Filter = (typeof FILTERS)[number]["value"];

function formatWhen(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function formatSessionDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/** Live status wins when Blockstead can reach it; the log-derived open session is
 * the fallback signal (e.g. the fake fixture, or a Minecraft version/bind that
 * doesn't answer the status protocol) — never treated as equal certainty. */
function isConsideredOnline(entry: RosterEntry): boolean {
  return entry.online === true || (entry.online == null && entry.tracked_online);
}

function statusLabel(entry: RosterEntry): string {
  if (entry.online === true) return "Online";
  if (entry.online === false) return "Offline";
  return entry.tracked_online ? "Likely online" : "Status unknown";
}

function seenNote(entry: RosterEntry): string {
  if (isConsideredOnline(entry)) {
    return entry.session_seconds != null ? `Online for ${formatSessionDuration(entry.session_seconds)}` : "Online now";
  }
  if (entry.last_seen) {
    const played = entry.session_seconds != null ? ` · played ${formatSessionDuration(entry.session_seconds)}` : "";
    return `Last seen ${formatWhen(entry.last_seen)}${played}`;
  }
  return "No recorded sessions";
}

function avatarUrl(uuid: string): string {
  return `https://crafatar.com/avatars/${uuid}?size=32&overlay`;
}

function Avatar({ entry }: { entry: RosterEntry }) {
  const [failed, setFailed] = useState(false);
  if (!entry.uuid || failed) {
    return <span className="roster-avatar roster-avatar--placeholder" aria-hidden="true">{entry.name.slice(0, 1).toUpperCase()}</span>;
  }
  return <img className="roster-avatar" src={avatarUrl(entry.uuid)} alt="" width={32} height={32} onError={() => setFailed(true)} />;
}

function RosterRow({
  entry,
  running,
  showAvatars,
  pending,
  onAction,
}: {
  entry: RosterEntry;
  running: boolean;
  showAvatars: boolean;
  pending: boolean;
  onAction: (action: PlayerAction, player: string) => void;
}) {
  const [confirming, setConfirming] = useState<"ban" | "kick" | null>(null);
  return <li className="roster-row">
    <div className="roster-row__identity">
      {showAvatars && <Avatar entry={entry} />}
      <div>
        <strong>{entry.name}</strong>
        <div className="roster-row__badges">
          {entry.allowlisted && <span className="roster-badge">Allowlisted</span>}
          {entry.operator && <span className="roster-badge roster-badge--op">Operator</span>}
          {entry.banned && <span className="roster-badge roster-badge--danger">Banned{entry.ban_reason ? `: ${entry.ban_reason}` : ""}</span>}
        </div>
      </div>
    </div>
    <div className="roster-row__status">
      <span className={`roster-status roster-status--${entry.online === true ? "online" : entry.online === false ? "offline" : "unknown"}`}>{statusLabel(entry)}</span>
      <small>{seenNote(entry)}</small>
    </div>
    <div className="roster-row__actions">
      {isConsideredOnline(entry) && (confirming === "kick"
        ? <Button className="button--danger button--small" disabled={pending} onClick={() => { onAction("kick", entry.name); setConfirming(null); }}>Confirm kick</Button>
        : <Button className="button--quiet button--small" disabled={!running || pending} onClick={() => setConfirming("kick")}>Kick</Button>)}
      {entry.banned
        ? <Button className="button--quiet button--small" disabled={!running || pending} onClick={() => onAction("pardon", entry.name)}>Unban</Button>
        : (confirming === "ban"
          ? <Button className="button--danger button--small" disabled={pending} onClick={() => { onAction("ban", entry.name); setConfirming(null); }}>Confirm ban</Button>
          : <Button className="button--quiet button--small" disabled={!running || pending} onClick={() => setConfirming("ban")}>Ban</Button>)}
    </div>
  </li>;
}

export function PlayersPanel({ profileId, running }: { profileId: string; running: boolean }) {
  const client = useQueryClient();
  const [player, setPlayer] = useState("");
  const [action, setAction] = useState<PlayerAction>("whitelist_add");
  const [confirmingBan, setConfirmingBan] = useState(false);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const roster = useQuery({
    queryKey: ["players-roster", profileId],
    queryFn: () => api<RosterView>(`/profiles/${profileId}/players/roster`),
    refetchInterval: running ? 15_000 : false,
  });
  const preferences = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => api<NotificationPreferences>("/notification-preferences"),
  });

  const act = useMutation({
    mutationFn: (payload: { action: PlayerAction; player: string }) =>
      api<{ command: string }>("/server/players", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: result => {
      setNotice(`Sent “${result.command}” to the server console.`);
      setPlayer("");
      void client.invalidateQueries({ queryKey: ["players-roster", profileId] });
    },
    onError: e => setNotice(e.message),
  });

  function submit(event: FormEvent) {
    event.preventDefault(); setNotice("");
    if (!/^[A-Za-z0-9_]{3,16}$/.test(player)) { setNotice("Player names use 3–16 letters, numbers, or underscores."); return; }
    if (action === "ban" && !confirmingBan) { setConfirmingBan(true); return; }
    setConfirmingBan(false); act.mutate({ action, player });
  }
  const valid = /^[A-Za-z0-9_]{3,16}$/.test(player);

  const entries = roster.data?.entries ?? [];
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (roster.data?.entries ?? [])
      .filter(entry => !term || entry.name.toLowerCase().includes(term))
      .filter(entry => {
        if (filter === "online") return isConsideredOnline(entry);
        if (filter === "allowlisted") return entry.allowlisted;
        if (filter === "operators") return entry.operator;
        if (filter === "banned") return entry.banned;
        return true;
      });
  }, [roster.data, search, filter]);

  const showAvatars = preferences.data?.show_player_avatars ?? false;

  return <section className="card players-workspace" id="players">
    <div className="section-heading"><div><p className="eyebrow">Player management</p><h2>Players</h2></div>
      {roster.data && <span className="section-count">
        {roster.data.status_available && roster.data.online_count != null
          ? `${roster.data.online_count} of ${roster.data.max_players ?? "?"} online`
          : "Live status unavailable"}
      </span>}
    </div>
    <p>Merges the allowlist, operator, and ban lists with what the running server currently reports. Join and leave times are tracked from the server's own log, when Blockstead recognizes its phrasing.</p>

    {roster.isLoading ? <p className="empty-note">Loading players…</p>
      : roster.error ? <p className="error" role="alert">{roster.error.message}</p>
        : <>
          <div className="roster-toolbar">
            <label className="roster-search">Search players<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Player name" /></label>
            <div className="history-filter" role="group" aria-label="Filter players">
              {FILTERS.map(item => <button key={item.value} type="button" className={filter === item.value ? "active" : ""} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}</button>)}
            </div>
          </div>
          {entries.length === 0
            ? <p className="empty-note">No players are allowlisted, operators, banned, or currently online.</p>
            : filtered.length === 0
              ? <p className="empty-note">No players match this search or filter.</p>
              : <ul className="roster-list">{filtered.map(entry => <RosterRow key={entry.name} entry={entry} running={running} showAvatars={showAvatars} pending={act.isPending} onAction={(actionValue, playerName) => { setNotice(""); act.mutate({ action: actionValue, player: playerName }); }} />)}</ul>}
        </>}

    <form className="inline-form" onSubmit={submit}>
      <label>Player name<input value={player} onChange={e => { setPlayer(e.target.value); setConfirmingBan(false); }} placeholder="Steve_Fixture" disabled={!running} /></label>
      <label>Action<select value={action} onChange={e => { setAction(e.target.value as PlayerAction); setConfirmingBan(false); }} disabled={!running}>{ACTIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <Button className={confirmingBan ? "button--danger" : ""} disabled={!running || !valid || act.isPending}>{confirmingBan ? "Confirm ban" : "Apply"}</Button>
    </form>
    {notice && <p className="muted-note" role="status">{notice}</p>}
    <small className="muted-note">{running ? "Actions are sent as guided console commands to the running server." : "Start the server to apply player actions. The roster stays readable while it is stopped."}</small>
  </section>;
}
