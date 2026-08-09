import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Account } from "../../api/client";
import { Button } from "../../components/Button";

export function PasswordPanel() {
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const change = useMutation({
    mutationFn: () => api<{ detail: string }>("/auth/password", { method: "POST", body: JSON.stringify({ password }) }),
    onSuccess: result => { setPassword(""); setNotice(result.detail); },
    onError: error => setNotice(error.message),
  });
  return <section className="card" aria-labelledby="password-heading"><p className="eyebrow">Your access</p><h2 id="password-heading">Change your password</h2><form className="inline-form" onSubmit={(event: FormEvent) => { event.preventDefault(); change.mutate(); }}><label>New password<input type="password" autoComplete="new-password" minLength={12} value={password} onChange={event => setPassword(event.target.value)} required /></label><Button disabled={change.isPending}>{change.isPending ? "Updating…" : "Change password"}</Button></form>{notice && <p className={notice.includes("updated") ? "success" : "error"} role="status">{notice}</p>}</section>;
}

export function AccountAccessPanel() {
  const client = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [recoveryToken, setRecoveryToken] = useState("");
  const [notice, setNotice] = useState("");
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api<Account[]>("/accounts") });
  const create = useMutation({
    mutationFn: () => api<Account>("/accounts", { method: "POST", body: JSON.stringify({ username, password }) }),
    onSuccess: async () => { setUsername(""); setPassword(""); setNotice("View-only account created."); await client.invalidateQueries({ queryKey: ["accounts"] }); },
    onError: error => setNotice(error.message),
  });
  const setStatus = useMutation({
    mutationFn: ({ account, disabled }: { account: Account; disabled: boolean }) => api<Account>(`/accounts/${account.id}/status`, { method: "POST", body: JSON.stringify({ disabled }) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["accounts"] }),
    onError: error => setNotice(error.message),
  });
  const remove = useMutation({
    mutationFn: (account: Account) => api<void>(`/accounts/${account.id}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["accounts"] }),
    onError: error => setNotice(error.message),
  });
  const recover = useMutation({
    mutationFn: (account: Account) => api<{ token: string; expires_at: string }>(`/accounts/${account.id}/recovery`, { method: "POST" }),
    onSuccess: result => { setRecoveryToken(result.token); setNotice(`Recovery token expires ${new Date(result.expires_at).toLocaleTimeString()}. Copy it to the helper securely; it is shown only once.`); },
    onError: error => setNotice(error.message),
  });
  return <section className="card" aria-labelledby="accounts-heading"><div className="section-heading"><div><p className="eyebrow">Trusted helpers</p><h2 id="accounts-heading">View-only accounts</h2></div><span>{accounts.data?.length ?? 0} account{accounts.data?.length === 1 ? "" : "s"}</span></div><p>Helpers can review operations summaries, but cannot open console, raw files, secrets, settings, recovery actions, or host controls.</p><form className="inline-form" onSubmit={(event: FormEvent) => { event.preventDefault(); create.mutate(); }}><label>Username<input autoCapitalize="none" value={username} onChange={event => setUsername(event.target.value)} minLength={3} maxLength={64} required /></label><label>Temporary password<input type="password" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} minLength={12} required /></label><Button disabled={create.isPending}>{create.isPending ? "Creating…" : "Create viewer"}</Button></form>{notice && <p className="muted-note" role="status">{notice}</p>}{recoveryToken && <div className="warning"><strong>One-time recovery token</strong><code>{recoveryToken}</code><small>Never paste this token into a command or shared log. It expires shortly and cannot be reused.</small></div>}<ul className="care-list">{accounts.data?.filter(account => account.role === "viewer").map(account => <li key={account.id}><div><strong>{account.username}</strong><small>{account.disabled ? "Disabled; sessions revoked" : "Enabled"}</small></div><div className="row-actions"><Button className="button--secondary button--small" onClick={() => setStatus.mutate({ account, disabled: !account.disabled })}>{account.disabled ? "Enable" : "Disable"}</Button><Button className="button--quiet button--small" onClick={() => recover.mutate(account)}>Issue recovery</Button><Button className="button--danger button--small" onClick={() => remove.mutate(account)}>Delete</Button></div></li>)}</ul></section>;
}
