import { useEffect, useState } from "react";
import { api, getCsrf } from "./api/client";
import { AuthPage } from "./features/auth/AuthPage";
import { Dashboard } from "./features/dashboard/Dashboard";

type View = "loading" | "setup" | "login" | "dashboard";
export default function App() {
  const [view, setView] = useState<View>("loading");
  useEffect(() => { api<{ needs_setup: boolean }>("/setup/status").then(result => { if (result.needs_setup) setView("setup"); else if (getCsrf()) api("/auth/me").then(() => setView("dashboard")).catch(() => setView("login")); else setView("login"); }).catch(() => setView("login")); }, []);
  if (view === "loading") return <main className="loading"><p>Opening Blockstead…</p></main>;
  if (view === "setup" || view === "login") return <AuthPage setup={view === "setup"} onSuccess={() => setView("dashboard")} />;
  return <Dashboard onLogout={() => setView("login")} />;
}
