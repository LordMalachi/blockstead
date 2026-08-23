import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type DiscordBotStatus,
  type DiscordConnection,
  type DiscordPairing,
  type Profile,
} from "../../api/client";
import { Button } from "../../components/Button";

type PrincipalDraft = { users: string; roles: string };
type ConnectionChange = {
  enabled?: boolean;
  share_address?: boolean;
  publish_address?: boolean;
  authorized_user_ids?: string[];
  authorized_role_ids?: string[];
};

const SNOWFLAKE = /^[0-9]{17,20}$/;

function parsePrincipalInput(value: string): string[] {
  const entries = value.split(/[\s,]+/).map(item => item.trim()).filter(Boolean);
  const result: string[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    if (!SNOWFLAKE.test(entry)) {
      throw new Error("Discord user and role IDs must be 17–20 digit numbers.");
    }
    if (!seen.has(entry)) {
      result.push(entry);
      seen.add(entry);
    }
  }
  if (result.length > 64) {
    throw new Error("You can approve at most 64 IDs in each list.");
  }
  return result;
}

function displayDelivery(connection: DiscordConnection): string {
  if (!connection.last_delivery_result) return "No status message delivery recorded yet.";
  const when = connection.last_delivery_at
    ? ` · ${new Date(connection.last_delivery_at).toLocaleString()}`
    : "";
  return `${connection.last_delivery_detail ?? "Status message delivery recorded."}${when}`;
}

function displayTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "Not recorded yet";
}

function pairingConfirmation(pairing: DiscordPairing): string {
  const roles = pairing.claimed_role_ids.length
    ? pairing.claimed_role_ids.join(", ")
    : "none observed";
  return [
    "Confirm this exact Discord pairing?",
    `Application: ${pairing.claimed_application_id}`,
    `Guild: ${pairing.claimed_guild_id}`,
    `Channel: ${pairing.claimed_channel_id}`,
    `Claiming user: ${pairing.claimed_user_id}`,
    `Claimed: ${displayTime(pairing.claimed_at)}`,
    `Observed roles (not automatically approved): ${roles}`,
  ].join("\n");
}

export function DiscordBotPanel() {
  const client = useQueryClient();
  const [profileId, setProfileId] = useState("");
  const [pairingCode, setPairingCode] = useState("");
  const [notice, setNotice] = useState("");
  const [principalDrafts, setPrincipalDrafts] = useState<Record<string, PrincipalDraft>>({});
  const status = useQuery({
    queryKey: ["discord-bot-status"],
    queryFn: () => api<DiscordBotStatus>("/discord/status"),
    refetchInterval: 10000,
  });
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: () => api<Profile[]>("/profiles"),
  });
  const data = status.data;
  const refresh = () => void client.invalidateQueries({ queryKey: ["discord-bot-status"] });

  const createPairing = useMutation({
    mutationFn: () => api<{ code: string; expires_at: string }>("/discord/pairings", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    }),
    onSuccess: result => {
      setPairingCode(result.code);
      setNotice(`Pairing code expires ${new Date(result.expires_at).toLocaleTimeString()}.`);
      refresh();
    },
    onError: error => setNotice(error.message),
  });

  const confirmPairing = useMutation({
    mutationFn: (id: string) => api<DiscordConnection>(
      `/discord/pairings/${id}/confirm`,
      { method: "POST" },
    ),
    onSuccess: () => {
      setNotice("Discord pairing confirmed.");
      refresh();
    },
    onError: error => setNotice(error.message),
  });

  const updateConnection = useMutation({
    mutationFn: ({ connection, change }: {
      connection: DiscordConnection;
      change: ConnectionChange;
    }) => api<DiscordConnection>(
      `/discord/connections/${connection.id}/status`,
      { method: "POST", body: JSON.stringify(change) },
    ),
    onSuccess: (_result, variables) => {
      setNotice("Discord connection updated.");
      setPrincipalDrafts(previous => {
        const next = { ...previous };
        delete next[variables.connection.id];
        return next;
      });
      refresh();
    },
    onError: error => setNotice(error.message),
  });

  const revokeConnection = useMutation({
    mutationFn: (connection: DiscordConnection) => api<void>(
      `/discord/connections/${connection.id}`,
      { method: "DELETE" },
    ),
    onSuccess: () => {
      setNotice("Discord connection revoked.");
      refresh();
    },
    onError: error => setNotice(error.message),
  });

  const rotateConnector = useMutation({
    mutationFn: () => api<{ installation_id: string; rotation_state: string; detail: string }>(
      "/discord/connector/rotate",
      { method: "POST" },
    ),
    onSuccess: result => {
      setNotice(result.detail);
      refresh();
    },
    onError: error => setNotice(error.message),
  });

  const draftFor = (connection: DiscordConnection): PrincipalDraft => principalDrafts[connection.id] ?? {
    users: connection.authorized_user_ids
      .filter(id => id !== connection.owner_user_id)
      .join(", "),
    roles: connection.authorized_role_ids.join(", "),
  };
  const updateDraft = (connection: DiscordConnection, field: keyof PrincipalDraft, value: string) => {
    const current = draftFor(connection);
    setPrincipalDrafts(previous => ({
      ...previous,
      [connection.id]: { ...current, [field]: value },
    }));
  };
  const savePrincipals = (connection: DiscordConnection) => {
    try {
      const draft = draftFor(connection);
      const users = [connection.owner_user_id, ...parsePrincipalInput(draft.users)];
      const roles = parsePrincipalInput(draft.roles);
      updateConnection.mutate({
        connection,
        change: {
          authorized_user_ids: [...new Set(users)],
          authorized_role_ids: roles,
        },
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The approved principal list is invalid.");
    }
  };
  const confirmClaim = (pairing: DiscordPairing) => {
    if (window.confirm(pairingConfirmation(pairing))) {
      confirmPairing.mutate(pairing.id);
    }
  };
  const revoke = (connection: DiscordConnection) => {
    if (window.confirm(
      `Permanently revoke the Discord connection for ${connection.profile_name}? `
      + "This terminal action removes the binding; a new pairing will be required.",
    )) {
      revokeConnection.mutate(connection);
    }
  };

  return <section className="card" aria-labelledby="discord-bot-heading">
    <div className="section-heading">
      <div><p className="eyebrow">Central Discord relay</p><h2 id="discord-bot-heading">Discord server status bot</h2></div>
      <span>{data?.bot_ready ? "Bot ready" : data?.relay_online ? "Discord unavailable" : "Needs relay"}</span>
    </div>
    <p>The shared Discord bot stays online on the relay. This Blockstead host makes an outbound connection and only sends the selected profile’s status.</p>
    {status.isLoading && <p className="muted-note" role="status">Checking Discord application configuration…</p>}
    {status.error && <p className="error" role="alert">{status.error.message}</p>}
    {data && <>
      <dl className="system-facts">
        <div><dt>Application ID</dt><dd><code>{data.application_id ?? "Not configured"}</code></dd></div>
        <div><dt>Public key</dt><dd>{data.public_key_configured ? "Configured" : data.public_key_error ?? "Not configured"}</dd></div>
        <div><dt>Relay URL</dt><dd><code>{data.relay_url ?? "Not configured"}</code></dd></div>
        <div><dt>Host-to-relay connector</dt><dd>{data.relay_online ? "Connected" : "Disconnected"}</dd></div>
        <div><dt>Discord Gateway</dt><dd>{data.discord_online ? "READY with healthy heartbeat" : "Not ready"}</dd></div>
        <div><dt>Operational bot</dt><dd>{data.bot_ready ? "Ready" : "Not ready"}</dd></div>
        <div><dt>Installation identity</dt><dd>{data.connector_configured ? "Configured" : "Generated on first start"}</dd></div>
      </dl>
      {data.application_error && <p className="error" role="alert">{data.application_error}</p>}
      {!data.relay_configured && <p className="warning" role="status">Set <code>BLOCKSTEAD_DISCORD_RELAY_URL</code> for the central relay and restart Blockstead. The Discord bot token belongs only on the relay.</p>}
      {data.legacy_token_present && <p className="warning" role="status">The old host-side Discord token setting is deprecated and ignored. Remove <code>BLOCKSTEAD_DISCORD_BOT_TOKEN</code> after migrating to the relay.</p>}
      {data.install_url && <p><a className="button button--secondary" href={data.install_url} target="_blank" rel="noreferrer">Install bot in Discord</a></p>}
      {data.relay_configured && <>
        <div className="row-actions">
          {data.connector_environment_managed
            ? <p className="muted-note">Connector rotation is managed by deployment settings.</p>
            : <Button className="button--secondary button--small" disabled={rotateConnector.isPending || !data.relay_online} onClick={() => { if (window.confirm("Rotate the generated Discord connector identity? The host will reconnect briefly.")) rotateConnector.mutate(); }}>{rotateConnector.isPending ? "Rotating…" : "Rotate connector identity"}</Button>}
        </div>
        <h3>Pair a server profile</h3>
        <p className="muted-note">In a new Discord channel, run <code>/blockstead setup</code> for the walkthrough. Then create a short-lived code here and run <code>/blockstead pair code:…</code> in that channel. Confirm the claimed channel here. Use one channel per Minecraft profile when a guild hosts multiple servers.</p>
        <form className="inline-form" onSubmit={event => { event.preventDefault(); createPairing.mutate(); }}>
          <label>Blockstead profile<select value={profileId} onChange={event => setProfileId(event.target.value)} required><option value="">Choose a profile…</option>{profiles.data?.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
          <Button disabled={createPairing.isPending || !profileId || !data.relay_online}>{createPairing.isPending ? "Creating…" : "Create pairing code"}</Button>
        </form>
        {pairingCode && <div className="warning"><strong>One-time pairing code</strong><code>{pairingCode}</code><small>Use it once in Discord. It is not stored in readable form and expires shortly.</small></div>}
        {data.pairings.length > 0 && <>
          <h3>Recent pairings</h3>
          <ul className="care-list">{data.pairings.map(pairing => <li key={pairing.id}>
            <div>
              <strong>{pairing.profile_name}</strong>
              <small>{pairing.status} · expires {displayTime(pairing.expires_at)}</small>
              {pairing.claimed ? <>
                <small>Application: <code>{pairing.claimed_application_id}</code></small>
                <small>Guild: <code>{pairing.claimed_guild_id}</code> · channel: <code>{pairing.claimed_channel_id}</code></small>
                <small>Claiming user: <code>{pairing.claimed_user_id}</code> · claimed {displayTime(pairing.claimed_at)}</small>
                <small>Observed roles (not approved automatically): {pairing.claimed_role_ids.length
                  ? pairing.claimed_role_ids.map(role => <code key={role}>{role} </code>)
                  : "none"}</small>
              </> : <small>Waiting for the Discord claim.</small>}
            </div>
            {pairing.status === "pending" && pairing.claimed && <Button className="button--secondary button--small" disabled={confirmPairing.isPending} onClick={() => confirmClaim(pairing)}>Review and confirm</Button>}
          </li>)}</ul>
        </>}
        {data.connections.length > 0 && <>
          <h3>Confirmed connections</h3>
          <ul className="care-list">{data.connections.map(connection => { const draft = draftFor(connection); return <li key={connection.id}>
            <div>
              <strong>{connection.profile_name}</strong>
              <small>{connection.enabled ? "Enabled" : "Disabled"}</small>
              <small>Application: <code>{connection.application_id}</code></small>
              <small>Guild: <code>{connection.guild_id}</code> · channel: <code>{connection.channel_id}</code></small>
              <small>Pairing owner: <code>{connection.owner_user_id}</code></small>
              <small>Host heartbeat: {displayTime(connection.last_heartbeat_at)}</small>
              <small>Relay heartbeat: {displayTime(connection.last_relay_heartbeat_at)}</small>
              <small>Status delivery: {displayDelivery(connection)}{connection.status_message_configured ? " · public status message configured" : " · waiting for first status message"}</small>
            </div>
            <div className="principal-controls"><label>Approved user IDs (owner is always retained)<input value={draft.users} placeholder="17–20 digit Discord user IDs" onChange={event => updateDraft(connection, "users", event.target.value)} /></label><label>Approved role IDs<input value={draft.roles} placeholder="17–20 digit Discord role IDs" onChange={event => updateDraft(connection, "roles", event.target.value)} /></label><Button className="button--secondary button--small" disabled={updateConnection.isPending} onClick={() => savePrincipals(connection)}>Save approved principals</Button></div>
            <div className="row-actions">
              <Button className="button--secondary button--small" disabled={updateConnection.isPending} onClick={() => updateConnection.mutate({ connection, change: { enabled: !connection.enabled } })}>{connection.enabled ? "Disable" : "Enable"}</Button>
              <Button className="button--secondary button--small" disabled={updateConnection.isPending} onClick={() => updateConnection.mutate({ connection, change: { share_address: !connection.share_address } })}>{connection.share_address ? "Disable /address sharing" : "Allow /address sharing"}</Button>
              <Button className="button--secondary button--small" disabled={updateConnection.isPending || !connection.share_address} onClick={() => updateConnection.mutate({ connection, change: { publish_address: !connection.publish_address } })}>{connection.publish_address ? "Hide address from status" : "Publish address in status"}</Button>
              <Button className="button--danger button--small" disabled={revokeConnection.isPending} onClick={() => revoke(connection)}>Revoke permanently</Button>
            </div>
          </li>; })}</ul>
        </>}
      </>}
      {notice && <p className="muted-note" role="status">{notice}</p>}
      <small className="muted-note">Discord exposes read-only status, player counts, and an owner-controlled address view. Server controls, raw console access, files, backups, and settings are not exposed through the bot.</small>
    </>}
  </section>;
}
