import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type PlayerAction, type PlayerFile, type PlayersView } from "../../api/client";
import { Button } from "../../components/Button";

const ACTIONS: { value: PlayerAction; label: string }[] = [
  { value: "whitelist_add", label: "Add to allowlist" },
  { value: "whitelist_remove", label: "Remove from allowlist" },
  { value: "op", label: "Make operator" },
  { value: "deop", label: "Remove operator" },
  { value: "ban", label: "Ban" },
  { value: "pardon", label: "Unban" },
];

function PlayerList({ title, file }: { title: string; file: PlayerFile }) {
  return <div className="player-list"><h3>{title} <span>{file.readable ? file.players.length : "–"}</span></h3>{!file.present ? <p className="empty-note">Not created yet.</p> : !file.readable ? <p className="empty-note">This file could not be read safely.</p> : file.players.length === 0 ? <p className="empty-note">Nobody listed.</p> : <ul>{file.players.map(player => <li key={player.name}><strong>{player.name}</strong>{player.level != null && <small>level {player.level}</small>}{player.reason && <small>{player.reason}</small>}</li>)}</ul>}</div>;
}

export function PlayersPanel({ profileId, running }: { profileId: string; running: boolean }) {
  const client = useQueryClient();
  const [player, setPlayer] = useState("");
  const [action, setAction] = useState<PlayerAction>("whitelist_add");
  const [confirmingBan, setConfirmingBan] = useState(false);
  const [notice, setNotice] = useState("");
  const players = useQuery({ queryKey: ["players", profileId], queryFn: () => api<PlayersView>(`/profiles/${profileId}/players`) });
  const act = useMutation({
    mutationFn: () => api<{ command: string }>("/server/players", { method: "POST", body: JSON.stringify({ action, player }) }),
    onSuccess: result => { setNotice(`Sent “${result.command}” to the server console.`); setPlayer(""); void client.invalidateQueries({ queryKey: ["players", profileId] }); },
    onError: e => setNotice(e.message),
  });
  function submit(event: FormEvent) {
    event.preventDefault(); setNotice("");
    if (!/^[A-Za-z0-9_]{3,16}$/.test(player)) { setNotice("Player names use 3–16 letters, numbers, or underscores."); return; }
    if (action === "ban" && !confirmingBan) { setConfirmingBan(true); return; }
    setConfirmingBan(false); act.mutate();
  }
  const valid = /^[A-Za-z0-9_]{3,16}$/.test(player);
  return <section className="card" id="players"><div className="section-heading"><div><p className="eyebrow">Player management</p><h2>Players</h2></div></div><p>These lists come straight from the server folder and are read without changing any file.</p>{players.data && <div className="player-lists"><PlayerList title="Allowlist" file={players.data.allowlist} /><PlayerList title="Operators" file={players.data.operators} /><PlayerList title="Banned" file={players.data.bans} /></div>}<form className="inline-form" onSubmit={submit}><label>Player name<input value={player} onChange={e => { setPlayer(e.target.value); setConfirmingBan(false); }} placeholder="Steve_Fixture" disabled={!running} /></label><label>Action<select value={action} onChange={e => { setAction(e.target.value as PlayerAction); setConfirmingBan(false); }} disabled={!running}>{ACTIONS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><Button className={confirmingBan ? "button--danger" : ""} disabled={!running || !valid || act.isPending}>{confirmingBan ? "Confirm ban" : "Apply"}</Button></form>{notice && <p className="muted-note" role="status">{notice}</p>}<small className="muted-note">{running ? "Actions are sent as guided console commands to the running server. The fixture answers in the live log without rewriting these files." : "Start the server to apply player actions. The lists stay readable while it is stopped."}</small></section>;
}
