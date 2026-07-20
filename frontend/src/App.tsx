import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, getCsrf, setOnAuthExpired } from "./api/client";
import { AuthPage } from "./features/auth/AuthPage";
import { ConsolePage } from "./features/console/ConsolePage";
import { HelpPage } from "./features/help/HelpPage";
import { WalkthroughProvider } from "./features/help/Walkthrough";
import { OverviewPage } from "./features/servers/OverviewPage";
import { ServerLayout } from "./features/servers/ServerLayout";
import { BackupsPage, ModsPage, PlayersPage, SchedulePage, SettingsPage } from "./features/servers/ServerPages";
import { ServersPage } from "./features/servers/ServersPage";
import { AppShell } from "./features/shell/AppShell";
import { SystemPage } from "./features/system/SystemPage";

type View = "loading" | "setup" | "login" | "dashboard";
export default function App() {
  const [view, setView] = useState<View>("loading");
  useEffect(() => { api<{ needs_setup: boolean }>("/setup/status").then(result => { if (result.needs_setup) setView("setup"); else if (getCsrf()) api("/auth/me").then(() => setView("dashboard")).catch(() => setView("login")); else setView("login"); }).catch(() => setView("login")); }, []);
  // A session that expires mid-use must return the owner to sign-in; otherwise the
  // dashboard keeps polling into 401s while showing frozen stats as if they were live.
  useEffect(() => {
    setOnAuthExpired(() => setView(current => current === "dashboard" ? "login" : current));
    return () => setOnAuthExpired(null);
  }, []);
  if (view === "loading") return <main className="loading"><p>Opening Blockstead…</p></main>;
  if (view === "setup" || view === "login") return <AuthPage setup={view === "setup"} onSuccess={() => setView("dashboard")} />;
  return <WalkthroughProvider><Routes>
    <Route element={<AppShell onLogout={() => setView("login")} />}>
      <Route index element={<Navigate to="/servers" replace />} />
      <Route path="servers" element={<ServersPage />} />
      <Route path="servers/:profileId" element={<ServerLayout />}>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="console" element={<ConsolePage />} />
        <Route path="players" element={<PlayersPage />} />
        <Route path="mods" element={<ModsPage />} />
        <Route path="backups" element={<BackupsPage />} />
        <Route path="schedule" element={<SchedulePage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="system" element={<SystemPage />} />
      <Route path="help" element={<HelpPage />} />
      <Route path="*" element={<Navigate to="/servers" replace />} />
    </Route>
  </Routes></WalkthroughProvider>;
}
