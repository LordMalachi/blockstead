import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useMatch } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, clearCsrf, type ProcessState, type Profile } from "../../api/client";
import { BrandMark } from "../../components/BrandMark";
import { Button } from "../../components/Button";
import { NavIcon } from "../../components/NavIcon";
import { StatusBadge } from "../../components/StatusBadge";
import { scopeFor } from "../servers/scope";
import { UpdateNotice } from "./UpdateNotice";

const workspaceNav = [
  { to: "/servers", label: "Servers", icon: "server", end: true },
  { to: "/system", label: "System", icon: "pulse", end: false },
  { to: "/help", label: "Help", icon: "help", end: false },
];
const serverNav = [
  { path: "overview", label: "Overview", icon: "grid" },
  { path: "console", label: "Console", icon: "terminal" },
  { path: "players", label: "Players", icon: "users" },
  { path: "mods", label: "Mods and plugins", icon: "blocks" },
  { path: "backups", label: "Backups", icon: "package" },
  { path: "schedule", label: "Schedule", icon: "clock" },
  { path: "settings", label: "Settings", icon: "sliders" },
];
const serverSoon = [
  { label: "Files", icon: "folder", note: "Later" },
];

function Soon({ label, icon, note }: { label: string; icon: string; note: string }) {
  return <span className="nav-disabled" aria-disabled="true"><NavIcon name={icon} /><span>{label}</span><small>{note}</small></span>;
}

export function AppShell({ onLogout }: { onLogout: () => void }) {
  const { pathname } = useLocation();
  const match = useMatch("/servers/:profileId/*");
  const profileId = match?.params.profileId ?? "";
  // Each page is its own route now, so it should open at the top rather than inherit
  // the scroll position of the page the owner came from.
  useEffect(() => { window.scrollTo({ top: 0, behavior: "instant" }); }, [pathname]);
  // Keep the open server's tools reachable from Servers and System too, so leaving a
  // workspace is never a one-way trip.
  const [recentId, setRecentId] = useState("");
  useEffect(() => { if (profileId) setRecentId(profileId); }, [profileId]);
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state"), refetchInterval: 1000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const profile = profiles.data?.find(entry => entry.id === (profileId || recentId));
  const snapshot = state.data ?? { state: "UNKNOWN" as const, pid: null, exit_code: null, reason: "Checking server state" };
  const scope = profileId && profile ? scopeFor(profile, snapshot, profiles.data ?? []) : null;

  async function logout() { await api("/auth/logout", { method: "POST" }); clearCsrf(); onLogout(); }

  return <div className="app-shell">
    <header className="topbar">
      <NavLink className="brand" to="/servers" aria-label="Blockstead home"><BrandMark /><span className="brand-copy">Blockstead<small>Minecraft server care</small></span></NavLink>
      {scope && <div className="server-summary"><span className="summary-label">{scope.profile.name}</span><StatusBadge state={scope.state} /></div>}
      <Button className={`button--quiet sign-out${scope ? "" : " sign-out--alone"}`} onClick={() => void logout()}>Sign out</Button>
    </header>
    <div className="layout">
      <aside className="sidebar">
        <nav aria-label="Main navigation">
          <p className="nav-heading">Workspace</p>
          {workspaceNav.map(item => <NavLink key={item.to} to={item.to} end={item.end} data-walkthrough={item.label.toLowerCase()} className={({ isActive }) => isActive ? "active" : ""}><NavIcon name={item.icon} /><span>{item.label}</span></NavLink>)}
          <Soon label="Activity" icon="history" note="Later" />
          {profile && <>
            <p className="nav-heading nav-heading--server" title={profile.name}>{profile.name}</p>
            {serverNav.map(item => <NavLink key={item.path} to={`/servers/${profile.id}/${item.path}`} className={({ isActive }) => isActive ? "active" : ""}><NavIcon name={item.icon} /><span>{item.label}</span></NavLink>)}
            {serverSoon.map(item => <Soon key={item.label} {...item} />)}
          </>}
        </nav>
        <div className="privacy-card" data-walkthrough="privacy"><span className="privacy-card__icon" aria-hidden="true">◆</span><div><strong>Local by design</strong><small>Your server data stays on this machine.</small></div></div>
      </aside>
      <main id="main">
        <UpdateNotice />
        <Outlet />
        <footer className="app-footer"><BrandMark small /><p><strong>Blockstead</strong><br />Quiet, local care for your Minecraft world.</p></footer>
      </main>
    </div>
  </div>;
}
