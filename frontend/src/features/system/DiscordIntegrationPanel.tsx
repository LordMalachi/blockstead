import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type NotificationDelivery, type NotificationIntegration } from "../../api/client";
import { Button } from "../../components/Button";

export function DiscordIntegrationPanel() {
  const client = useQueryClient();
  const [url, setUrl] = useState("");
  const [notice, setNotice] = useState("");
  const integrations = useQuery({ queryKey: ["notification-integrations"], queryFn: () => api<NotificationIntegration[]>("/notification-integrations") });
  const integration = integrations.data?.[0];
  const deliveries = useQuery({ queryKey: ["notification-deliveries", integration?.id], queryFn: () => api<NotificationDelivery[]>(`/notification-integrations/${integration?.id}/deliveries`), enabled: !!integration });
  const create = useMutation({
    mutationFn: () => api<NotificationIntegration>("/notification-integrations", { method: "POST", body: JSON.stringify({ webhook_url: url }) }),
    onSuccess: async () => { setUrl(""); setNotice("Discord notifications configured. Local alert preferences still decide what is sent."); await client.invalidateQueries({ queryKey: ["notification-integrations"] }); },
    onError: error => setNotice(error.message),
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api<NotificationIntegration>(`/notification-integrations/${integration?.id}/status`, { method: "POST", body: JSON.stringify({ enabled }) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["notification-integrations"] }),
    onError: error => setNotice(error.message),
  });
  const test = useMutation({
    mutationFn: () => api<unknown>(`/notification-integrations/${integration?.id}/test`, { method: "POST" }),
    onSuccess: result => { setNotice(`Test delivery: ${JSON.stringify(result)}`); void client.invalidateQueries({ queryKey: ["notification-deliveries", integration?.id] }); },
    onError: error => setNotice(error.message),
  });
  const remove = useMutation({
    mutationFn: () => api<void>(`/notification-integrations/${integration?.id}`, { method: "DELETE" }),
    onSuccess: async () => { setNotice("Discord integration removed."); await client.invalidateQueries({ queryKey: ["notification-integrations"] }); },
    onError: error => setNotice(error.message),
  });
  return <section className="card" aria-labelledby="discord-heading"><div className="section-heading"><div><p className="eyebrow">Outbound alerts</p><h2 id="discord-heading">Discord notifications</h2></div><span>{integration ? (integration.enabled ? "Enabled" : "Disabled") : "Not configured"}</span></div><p>Only redacted summaries of crashes, failed backups, failed automations, low disk space, and completed updates are queued. Webhooks must be public HTTPS Discord endpoints; delivery retries are durable and bounded.</p>{!integration && <form className="inline-form" onSubmit={event => { event.preventDefault(); create.mutate(); }}><label>Discord webhook URL<input type="url" placeholder="https://discord.com/api/webhooks/..." value={url} onChange={event => setUrl(event.target.value)} required /></label><Button disabled={create.isPending}>{create.isPending ? "Checking…" : "Save webhook"}</Button></form>}{integration && <><div className="row-actions"><code>{integration.webhook_display}</code><Button className="button--secondary button--small" onClick={() => toggle.mutate(!integration.enabled)}>{integration.enabled ? "Disable" : "Enable"}</Button><Button className="button--secondary button--small" onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? "Sending…" : "Send test"}</Button><Button className="button--danger button--small" onClick={() => remove.mutate()}>Remove</Button></div><h3>Delivery history</h3>{deliveries.data?.length ? <ul className="care-list">{deliveries.data.map(item => <li key={item.id}><div><strong>{item.status}</strong><small>{item.detail}</small></div><span>{item.attempts} attempt{item.attempts === 1 ? "" : "s"}</span></li>)}</ul> : <p className="empty-note">No deliveries recorded yet.</p>}</>}{notice && <p className="muted-note" role="status">{notice}</p>}<small className="muted-note">Manage alert categories in Activity → Local alerts. Blockstead never sends paths, player IPs, secrets, raw logs, or credentials.</small></section>;
}
