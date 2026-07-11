import { useState, type FormEvent } from "react";
import { api, setCsrf, type Session } from "../../api/client";
import { Button } from "../../components/Button";

export function AuthPage({ setup, onSuccess }: { setup: boolean; onSuccess: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      const session = await api<Session>(setup ? "/setup/admin" : "/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
      if (session.csrf_token) setCsrf(session.csrf_token);
      onSuccess();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to continue."); }
    finally { setBusy(false); }
  }
  return <main className="auth-shell"><section className="auth-card" aria-labelledby="auth-title"><div className="brand-mark" aria-hidden="true">B</div><p className="eyebrow">Local server care</p><h1 id="auth-title">{setup ? "Welcome to Blockstead" : "Welcome back"}</h1><p>{setup ? "Create the administrator who will manage this machine." : "Sign in to manage your Minecraft server."}</p><form onSubmit={event => { void submit(event); }}><label>Username<input autoComplete="username" required minLength={3} value={username} onChange={e => setUsername(e.target.value)} /></label><label>Password<input type="password" autoComplete={setup ? "new-password" : "current-password"} required minLength={12} value={password} onChange={e => setPassword(e.target.value)} /></label>{error && <div className="error" role="alert">{error}</div>}<Button disabled={busy}>{busy ? "Working…" : setup ? "Create administrator" : "Sign in"}</Button></form><p className="privacy-note">Blockstead stays on this computer unless you explicitly enable LAN access.</p></section></main>;
}
