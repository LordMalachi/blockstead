import { useState, type FormEvent } from "react";
import { api, setCsrf, type Session } from "../../api/client";
import { BrandMark } from "../../components/BrandMark";
import { Button } from "../../components/Button";
import "./setup.css";

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
  return <main className="auth-shell">
    <section className="auth-intro" aria-label="About Blockstead">
      <a className="auth-brand" href="/" aria-label="Blockstead home"><BrandMark /><span>Blockstead</span></a>
      <div className="auth-intro__copy">
        <p className="eyebrow">Your world. Your machine.</p>
        <h2>Run your Minecraft server with confidence.</h2>
        <p>Start, stop, schedule, and care for your server from one calm local dashboard.</p>
        <ul className="feature-list"><li><span>01</span>Safe server controls</li><li><span>02</span>Live console and players</li><li><span>03</span>Private by default</li></ul>
      </div>
      <p className="auth-intro__footer">Built for the person who keeps the world running.</p>
    </section>
    <section className="auth-panel">
      <div className="auth-card" aria-labelledby="auth-title">
        <div className="auth-card__mobile-brand"><BrandMark /><strong>Blockstead</strong></div>
        <p className="eyebrow">{setup ? "Let’s get you settled" : "Local server care"}</p>
        <h1 id="auth-title">{setup ? "Welcome to Blockstead" : "Welcome back"}</h1>
        <p>{setup ? "Create the administrator for this machine. You’ll add your server on the next screen." : "Sign in to manage your Minecraft server."}</p>
        {setup && <ol className="setup-steps"><li><span>1</span><div><strong>Create your account</strong><small>This is the local Blockstead administrator.</small></div></li><li><span>2</span><div><strong>Add your server folder</strong><small>Blockstead scans it without changing files.</small></div></li><li><span>3</span><div><strong>Review and start</strong><small>Accept the EULA, check readiness, and launch.</small></div></li></ol>}
        <form onSubmit={event => { void submit(event); }}>
          <label>Username<input autoComplete="username" required minLength={3} value={username} onChange={e => setUsername(e.target.value)} placeholder="Your admin name" /></label>
          <label>Password<input type="password" autoComplete={setup ? "new-password" : "current-password"} required minLength={12} value={password} onChange={e => setPassword(e.target.value)} placeholder="12 characters or more" /></label>
          {error && <div className="error" role="alert">{error}</div>}
          <Button disabled={busy}>{busy ? "Working…" : setup ? "Create administrator" : "Sign in"}</Button>
        </form>
        <p className="privacy-note"><span aria-hidden="true">◆</span> Blockstead stays on this computer unless you explicitly enable LAN access.</p>
      </div>
    </section>
  </main>;
}
