import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type LogEvent } from "../../api/client";
import { Button } from "../../components/Button";
import { useServerScope } from "../servers/scope";

const quickCommands = [
  { label: "Who is online?", command: "list" },
  { label: "Broadcast hello", command: "say Hello from Blockstead" },
  { label: "Show allowlist", command: "whitelist list" },
];

export function ConsolePage() {
  const scope = useServerScope();
  const client = useQueryClient();
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [command, setCommand] = useState("");
  const [notice, setNotice] = useState("");
  const send = useMutation({
    mutationFn: (line: string) => api<unknown>("/server/command", { method: "POST", body: JSON.stringify({ command: line }) }),
    onSuccess: () => { setNotice(""); void client.invalidateQueries({ queryKey: ["state"] }); },
    onError: error => setNotice(error.message),
  });

  useEffect(() => { api<LogEvent[]>("/server/logs").then(setLogs).catch(() => undefined); }, []);
  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/api/v1/server/logs/ws`);
    socket.onmessage = event => {
      const payload: unknown = event.data;
      if (typeof payload === "string") setLogs(current => [...current.slice(-399), JSON.parse(payload) as LogEvent]);
    };
    return () => socket.close();
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!command.trim()) return;
    send.mutate(command);
    setCommand("");
  }

  // The managed process writes one log stream. Showing it under a profile that does
  // not own that process would attribute another server's output to this one.
  const lines = scope.isActive ? logs : [];
  return <section className="card console" id="console">
    <div className="section-heading"><div><p className="eyebrow">{scope.profile.name}</p><h2>Live server log</h2></div><span className="live-count"><i />{lines.length} lines</span></div>
    <div className="log" role="log" aria-live="polite">{lines.length ? lines.map(entry => <div key={entry.sequence}><time>{new Date(entry.timestamp).toLocaleTimeString()}</time><span>{entry.line}</span></div>) : <p className="empty">{scope.occupant ? `The log belongs to ${scope.occupant.name}, which is the server running right now.` : "Start this server to see its logs here."}</p>}</div>
    <div className="quick-commands" aria-label="Guided commands">{quickCommands.map(item => <Button key={item.command} className="button--secondary button--small" disabled={!scope.running} onClick={() => send.mutate(item.command)}>{item.label}</Button>)}</div>
    <form className="command" onSubmit={submit}><label htmlFor="command">Minecraft console command</label><div><input id="command" value={command} onChange={event => setCommand(event.target.value)} disabled={!scope.running} placeholder="give PlayerName minecraft:diamond 64" /><Button disabled={!scope.running}>Send command</Button></div><small>Any one-line vanilla Minecraft server command is sent to {scope.profile.name}—not to an operating-system shell.</small></form>
    {notice && <p className="error" role="alert">{notice}</p>}
  </section>;
}
