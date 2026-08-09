import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, getCsrf, setOnAuthExpired, type AppRole, type Session } from "./api/client";
import { AuthPage } from "./features/auth/AuthPage";
import { ActivityPage } from "./features/activity/ActivityPage";
import { ConsolePage } from "./features/console/ConsolePage";
import { HelpPage } from "./features/help/HelpPage";
import { WalkthroughProvider } from "./features/help/Walkthrough";
import { OverviewPage } from "./features/servers/OverviewPage";
import { ServerLayout } from "./features/servers/ServerLayout";
import { BackupsPage, FilesPage, MaintenancePage, ModsPage, PlayersPage, SchedulePage, SettingsPage, WorldCarePage } from "./features/servers/ServerPages";
import { ServersPage } from "./features/servers/ServersPage";
import { AppShell } from "./features/shell/AppShell";
import { useRole } from "./features/shell/role";
import { SystemPage } from "./features/system/SystemPage";
import { AccountPage } from "./features/system/AccountPage";

type View = "loading" | "setup" | "login" | "dashboard";
function OwnerRoute({ children }: { children: ReactNode }) {
  return useRole() === "owner" ? children : <Navigate to="/servers" replace />;
}
export default function App() {
  const [view, setView] = useState<View>("loading");
  const [role, setRole] = useState<AppRole>("owner");
  useEffect(() => { api<{ needs_setup: boolean }>("/setup/status").then(result => { if (result.needs_setup) setView("setup"); else if (getCsrf()) api<Session>("/auth/me").then(session => { setRole(session.role ?? "owner"); setView("dashboard"); }).catch(() => setView("login")); else setView("login"); }).catch(() => setView("login")); }, []);
  // A session that expires mid-use must return the owner to sign-in; otherwise the
  // dashboard keeps polling into 401s while showing frozen stats as if they were live.
  useEffect(() => {
    setOnAuthExpired(() => setView(current => current === "dashboard" ? "login" : current));
    return () => setOnAuthExpired(null);
  }, []);
  if (view === "loading") return <main className="loading"><p>Opening Blockstead…</p></main>;
  if (view === "setup" || view === "login") return <AuthPage setup={view === "setup"} onSuccess={session => { if (session?.role) setRole(session.role); else void api<Session>("/auth/me").then(current => setRole(current.role ?? "owner")); setView("dashboard"); }} />;
  return <WalkthroughProvider><Routes>
    <Route element={<AppShell role={role} onLogout={() => { setRole("owner"); setView("login"); }} />}>
      <Route index element={<Navigate to="/servers" replace />} />
      <Route path="servers" element={<ServersPage />} />
      <Route path="servers/:profileId" element={<ServerLayout />}>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="console" element={<OwnerRoute><ConsolePage /></OwnerRoute>} />
        <Route path="players" element={<PlayersPage />} />
        <Route path="mods" element={<OwnerRoute><ModsPage /></OwnerRoute>} />
        <Route path="backups" element={<BackupsPage />} />
        <Route path="maintenance" element={<OwnerRoute><MaintenancePage /></OwnerRoute>} />
        <Route path="schedule" element={<OwnerRoute><SchedulePage /></OwnerRoute>} />
        <Route path="settings" element={<OwnerRoute><SettingsPage /></OwnerRoute>} />
        <Route path="files" element={<OwnerRoute><FilesPage /></OwnerRoute>} />
        <Route path="world-care" element={<WorldCarePage />} />
      </Route>
      <Route path="system" element={<OwnerRoute><SystemPage /></OwnerRoute>} />
      <Route path="account" element={<AccountPage />} />
      <Route path="activity" element={<ActivityPage />} />
      <Route path="help" element={<HelpPage />} />
      <Route path="*" element={<Navigate to="/servers" replace />} />
    </Route>
  </Routes></WalkthroughProvider>;
}
