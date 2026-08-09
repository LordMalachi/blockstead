import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type DiscordBotStatus, type DiscordConnection, type Profile } from "../../api/client";
import { Button } from "../../components/Button";

export function DiscordBotPanel() {
  const client = useQueryClient();
  const [profileId, setProfileId] = useState("");
  const [pairingCode, setPairingCode] = useState("");
  const [notice, setNotice] = useState("");
  const status = useQuery({ queryKey: ["discord-bot-status"], queryFn: () => api<DiscordBotStatus>("/discord/status"), refetchInterval: 10000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const data = status.data;
  const refresh = () => void client.invalidateQueries({ queryKey: ["discord-bot-status"] });
  const createPairing = useMutation({
    mutationFn: () => api<{ code: string; expires_at: string }>("/discord/pairings", { method: "POST", body: JSON.stringify({ profile_id: profileId }) }),
    onSuccess: result => { setPairingCode(result.code); setNotice(`Pairing code expires ${new Date(result.expires_at).toLocaleTimeString()}.`); refresh(); },
    onError: error => setNotice(error.message),
  });
  const confirmPairing = useMutation({
    mutationFn: (id: string) => api<DiscordConnection>(`/discord/pairings/${id}/confirm`, { method: "POST" }),
    onSuccess: () => { setNotice("Discord pairing confirmed."); refresh(); },
    onError: error => setNotice(error.message),
  });
  const updateConnection = useMutation({
    mutationFn: ({ connection, change }: { connection: DiscordConnection; change: { enabled?: boolean; publish_address?: boolean } }) => api<DiscordConnection>(`/discord/connections/${connection.id}/status`, { method: "POST", body: JSON.stringify(change) }),
    onSuccess: () => { setNotice("Discord connection updated."); refresh(); },
    onError: error => setNotice(error.message),
  });
  const revokeConnection = useMutation({
    mutationFn: (connection: DiscordConnection) => api<void>(`/discord/connections/${connection.id}`, { method: "DELETE" }),
    onSuccess: () => { setNotice("Discord connection revoked."); refresh(); },
    onError: error => setNotice(error.message),
  });

  return <section className="card" aria-labelledby="discord-bot-heading">
    <div className="section-heading"><div><p className="eyebrow">Central Discord relay</p><h2 id="discord-bot-heading">Discord server status bot</h2></div><span>{data?.relay_online ? "Online" : "Needs relay"}</span></div>
    <p>The shared Discord bot stays online on the relay. This Blockstead host makes an outbound connection and only sends the selected profile’s status.</p>
    {status.isLoading && <p className="muted-note" role="status">Checking Discord application configuration…</p>}
    {status.error && <p className="error" role="alert">{status.error.message}</p>}
    {data && <>
      <dl className="system-facts">
        <div><dt>Application ID</dt><dd><code>{data.application_id ?? "Not configured"}</code></dd></div>
        <div><dt>Public key</dt><dd>{data.public_key_configured ? "Configured" : data.public_key_error ?? "Not configured"}</dd></div>
        <div><dt>Relay URL</dt><dd><code>{data.relay_url ?? "Not configured"}</code></dd></div>
        <div><dt>Relay connection</dt><dd>{data.relay_online ? "Connected" : "Disconnected"}</dd></div>
        <div><dt>Installation identity</dt><dd>{data.connector_configured ? "Configured" : "Generated on first start"}</dd></div>
      </dl>
      {data.application_error && <p className="error" role="alert">{data.application_error}</p>}
      {!data.relay_configured && <p className="warning" role="status">Set <code>BLOCKSTEAD_DISCORD_RELAY_URL</code> for the central relay and restart Blockstead. The Discord bot token belongs only on the relay.</p>}
      {data.legacy_token_present && <p className="warning" role="status">The old host-side Discord token setting is deprecated and ignored. Remove <code>BLOCKSTEAD_DISCORD_BOT_TOKEN</code> after migrating to the relay.</p>}
      {data.install_url && <p><a className="button button--secondary" href={data.install_url} target="_blank" rel="noreferrer">Install bot in Discord</a></p>}
      {data.relay_configured && <>
        <h3>Pair a server profile</h3>
        <p className="muted-note">In a new Discord channel, run <code>/blockstead setup</code> for the walkthrough. Then create a short-lived code here and run <code>/blockstead pair code:…</code> in that channel. Confirm the claimed channel here. Use one channel per Minecraft profile when a guild hosts multiple servers.</p>
        <form className="inline-form" onSubmit={event => { event.preventDefault(); createPairing.mutate(); }}>
          <label>Blockstead profile<select value={profileId} onChange={event => setProfileId(event.target.value)} required><option value="">Choose a profile…</option>{profiles.data?.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
          <Button disabled={createPairing.isPending || !profileId}>{createPairing.isPending ? "Creating…" : "Create pairing code"}</Button>
        </form>
        {pairingCode && <div className="warning"><strong>One-time pairing code</strong><code>{pairingCode}</code><small>Use it once in Discord. It is not stored in readable form and expires shortly.</small></div>}
        {data.pairings.length > 0 && <><h3>Recent pairings</h3><ul className="care-list">{data.pairings.map(pairing => <li key={pairing.id}><div><strong>{pairing.profile_name}</strong><small>{pairing.status}{pairing.claimed ? ` · claimed in channel ${pairing.claimed_channel_id}` : " · waiting for Discord"}</small></div>{pairing.status === "pending" && pairing.claimed && <Button className="button--secondary button--small" disabled={confirmPairing.isPending} onClick={() => confirmPairing.mutate(pairing.id)}>Confirm pairing</Button>}</li>)}</ul></>}
        {data.connections.length > 0 && <><h3>Confirmed connections</h3><ul className="care-list">{data.connections.map(connection => <li key={connection.id}><div><strong>{connection.profile_name}</strong><small>{connection.enabled ? "Enabled" : "Revoked"} · guild {connection.guild_id} · channel {connection.channel_id}</small></div><div className="row-actions"><Button className="button--secondary button--small" disabled={updateConnection.isPending} onClick={() => updateConnection.mutate({ connection, change: { enabled: !connection.enabled } })}>{connection.enabled ? "Disable" : "Enable"}</Button><Button className="button--secondary button--small" disabled={updateConnection.isPending || !connection.enabled} onClick={() => updateConnection.mutate({ connection, change: { publish_address: !connection.publish_address } })}>{connection.publish_address ? "Hide address" : "Share address"}</Button><Button className="button--danger button--small" disabled={revokeConnection.isPending || !connection.enabled} onClick={() => revokeConnection.mutate(connection)}>Revoke</Button></div></li>)}</ul></>}
      </>}
      {notice && <p className="muted-note" role="status">{notice}</p>}
      <small className="muted-note">Discord exposes read-only status, player counts, and an owner-controlled address view. Server controls, raw console access, files, backups, and settings are not exposed through the bot.</small>
    </>}
  </section>;
}
