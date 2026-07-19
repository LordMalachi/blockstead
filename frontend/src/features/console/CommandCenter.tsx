import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  api,
  type CommandArgument,
  type CommandCatalog,
  type CommandOption,
  type GuidedCommand,
  type PlayersView,
} from "../../api/client";
import { Button } from "../../components/Button";

type Values = Record<string, string>;

function normalizeOptions(options: CommandArgument["options"] = []): CommandOption[] {
  return options.map(option => typeof option === "string" ? { value: option, label: option } : option);
}

function SearchableOptions({ argument, options, value, onChange }: {
  argument: CommandArgument;
  options: CommandOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const needle = value.toLowerCase();
  const matches = options.filter(option => `${option.label} ${option.value}`.toLowerCase().includes(needle)).slice(0, 30);
  const listId = `command-options-${argument.key}`;
  return <div className="command-option-search">
    <input
      value={value}
      aria-label={argument.label}
      placeholder={argument.placeholder ?? `Search ${argument.label.toLowerCase()}…`}
      role="combobox"
      aria-expanded={open}
      aria-controls={listId}
      aria-autocomplete="list"
      onFocus={() => setOpen(true)}
      onBlur={() => window.setTimeout(() => setOpen(false), 120)}
      onChange={event => { onChange(event.target.value); setOpen(true); }}
    />
    {open && <div className="command-option-list" role="listbox" id={listId}>
      {matches.length ? matches.map(option => <button
        type="button"
        role="option"
        aria-selected={option.value === value}
        key={option.value}
        onMouseDown={event => event.preventDefault()}
        onClick={() => { onChange(option.value); setOpen(false); }}
      >
        <span className="command-option-icon" aria-hidden="true">{option.icon ?? "◇"}</span>
        <span><strong>{option.label}</strong><small>{option.value}</small></span>
      </button>) : <p>No listed matches. You can still enter an exact namespaced ID.</p>}
      {options.length > matches.length && <small className="command-option-limit">Showing the first {matches.length} matches—keep typing to narrow the list.</small>}
    </div>}
  </div>;
}

function ArgumentField({ argument, value, playerOptions, onChange }: {
  argument: CommandArgument;
  value: string;
  playerOptions: CommandOption[];
  onChange: (value: string) => void;
}) {
  const options = argument.source === "players" ? playerOptions : normalizeOptions(argument.options);
  if (argument.kind === "choice" || argument.kind === "boolean") {
    const choices = argument.kind === "boolean" ? ["true", "false"] : options.map(option => option.value);
    return <div className="command-choice-list">{choices.map(choice => <button
      type="button"
      className={value === choice ? "active" : ""}
      aria-pressed={value === choice}
      key={choice}
      onClick={() => onChange(choice)}
    >{choice}</button>)}</div>;
  }
  if (options.length > 5 || argument.kind === "resource") {
    return <SearchableOptions argument={argument} options={options} value={value} onChange={onChange} />;
  }
  return <>
    <input
      type={argument.kind === "integer" ? "number" : "text"}
      aria-label={argument.label}
      value={value}
      min={argument.minimum}
      max={argument.maximum}
      maxLength={argument.max_length}
      placeholder={argument.placeholder}
      onChange={event => onChange(event.target.value)}
      list={options.length ? `command-${argument.key}-values` : undefined}
    />
    {options.length > 0 && <datalist id={`command-${argument.key}-values`}>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</datalist>}
    {argument.suggestions && <div className="command-number-suggestions">{argument.suggestions.map(suggestion => <button type="button" key={suggestion} onClick={() => onChange(String(suggestion))}>{suggestion}</button>)}</div>}
  </>;
}

function commandPreview(command: GuidedCommand, values: Values): string {
  const parts = command.root.split(" ");
  for (const argument of command.arguments) {
    const value = values[argument.key]?.trim();
    if (!value) break;
    parts.push(value);
  }
  return parts.join(" ");
}

export function CommandCenter({ profileId, running }: { profileId: string; running: boolean }) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [values, setValues] = useState<Values>({});
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState("");
  const catalog = useQuery({ queryKey: ["command-catalog", profileId], queryFn: () => api<CommandCatalog>(`/profiles/${profileId}/commands`) });
  const players = useQuery({ queryKey: ["players", profileId], queryFn: () => api<PlayersView>(`/profiles/${profileId}/players`) });
  const commands = useMemo(() => catalog.data?.commands ?? [], [catalog.data?.commands]);
  const selected = commands.find(command => command.id === selectedId) ?? null;
  const categories = ["All", ...Array.from(new Set(commands.map(command => command.category)))];
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return commands.filter(command => (category === "All" || command.category === category) && (!needle || `${command.label} ${command.root} ${command.description} ${command.category}`.toLowerCase().includes(needle)));
  }, [category, commands, search]);
  const playerOptions = useMemo(() => {
    const names = new Set<string>();
    for (const file of players.data ? [players.data.allowlist, players.data.operators, players.data.bans] : []) {
      for (const player of file.players) names.add(player.name);
    }
    return [
      { value: "@a", label: "All players", icon: "◎" },
      { value: "@p", label: "Nearest player", icon: "◉" },
      { value: "@r", label: "Random player", icon: "◌" },
      ...Array.from(names).sort().map(name => ({ value: name, label: name, icon: "♟" })),
    ];
  }, [players.data]);
  const send = useMutation({
    mutationFn: ({ command, confirmed }: { command: GuidedCommand; confirmed: boolean }) => api<{ command: string }>("/server/guided-command", { method: "POST", body: JSON.stringify({ profile_id: profileId, command_id: command.id, values, confirmed }) }),
    onSuccess: result => { setNotice(`Sent “${result.command}” to the server.`); setConfirming(false); },
    onError: error => { setNotice(error.message); setConfirming(false); },
  });

  const ready = selected?.arguments.every(argument => !argument.required || Boolean(values[argument.key]?.trim())) ?? false;
  function choose(command: GuidedCommand) {
    setSelectedId(command.id);
    setValues({});
    setConfirming(false);
    setNotice("");
  }
  function submit() {
    if (!selected || !ready) return;
    if (selected.safety !== "normal" && !confirming) { setConfirming(true); return; }
    send.mutate({ command: selected, confirmed: confirming });
  }

  return <section className="command-center" aria-labelledby="command-center-title">
    <div className="command-center-heading">
      <div><p className="eyebrow">Guided console</p><h3 id="command-center-title">Command center</h3><p>Choose an action, fill in its values, and review the exact Minecraft command.</p></div>
      {catalog.data && <span title="More commands can be entered through the advanced raw console.">{catalog.data.complete ? "Live catalog" : "Curated catalog"}</span>}
    </div>
    <div className="command-browser">
      <div className="command-library">
        <label className="command-search">Search commands<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Try item, weather, player…" /></label>
        <div className="command-categories" aria-label="Command categories">{categories.map(item => <button type="button" className={category === item ? "active" : ""} aria-pressed={category === item} key={item} onClick={() => setCategory(item)}>{item}</button>)}</div>
        {catalog.isLoading ? <p className="empty-note">Loading guided commands…</p> : catalog.error ? <p className="error" role="alert">{catalog.error.message}</p> : <div className="command-cards">{filtered.map(command => <button
          type="button"
          className={selected?.id === command.id ? "active" : ""}
          title={command.description}
          key={command.id}
          onClick={() => choose(command)}
        ><span><strong>{command.label}</strong><small>{command.description}</small></span><code>{command.root}</code></button>)}{filtered.length === 0 && <p className="empty-note">No guided commands match that search. The advanced console can still send any command.</p>}</div>}
      </div>
      <div className="command-builder">
        {!selected ? <div className="command-builder-empty"><span aria-hidden="true">›_</span><strong>Choose a command</strong><p>Its required values will appear here.</p></div> : <>
          <div className="command-builder-title"><div><small>{selected.category}</small><h4>{selected.label}</h4></div>{selected.safety !== "normal" && <span className={`command-safety command-safety--${selected.safety}`}>{selected.safety === "danger" ? "Confirmation required" : "Review required"}</span>}</div>
          <p>{selected.description}</p>
          <div className="command-fields">{selected.arguments.length ? selected.arguments.map(argument => <label key={argument.key}>{argument.label}{!argument.required && <span>optional</span>}<ArgumentField argument={argument} value={values[argument.key] ?? ""} playerOptions={argument.allow_selectors === false ? playerOptions.filter(option => !option.value.startsWith("@")) : playerOptions} onChange={value => { setValues(current => ({ ...current, [argument.key]: value })); setConfirming(false); setNotice(""); }} /></label>) : <p className="command-no-fields">This command does not need any additional values.</p>}</div>
          <div className="command-preview"><span>Command preview</span><code>{commandPreview(selected, values)}</code></div>
          {confirming && <div className="command-confirm" role="alert"><strong>Check this command before sending it.</strong><span>{selected.safety === "danger" ? "This action affects player access or permissions." : "This action changes server or player state."}</span></div>}
          <div className="command-builder-actions"><Button disabled={!running || !ready || send.isPending} className={confirming && selected.safety === "danger" ? "button--danger" : ""} onClick={submit}>{send.isPending ? "Sending…" : confirming ? "Confirm and send" : "Review and send"}</Button><small>{running ? "Sent to this running server only." : "Start this server to send commands."}</small></div>
        </>}
        {notice && <p className={send.isError ? "error" : "success"} role="status">{notice}</p>}
      </div>
    </div>
  </section>;
}
