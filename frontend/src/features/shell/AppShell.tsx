import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useMatch } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, clearCsrf, type LocalNotifications, type ProcessState, type Profile } from "../../api/client";
import { BrandMark } from "../../components/BrandMark";
import { Button } from "../../components/Button";
import { NavIcon } from "../../components/NavIcon";
import { StatusBadge } from "../../components/StatusBadge";
import { scopeFor } from "../servers/scope";
import { UpdateNotice } from "./UpdateNotice";

const workspaceNav = [
  { to: "/servers", label: "Servers", icon: "server", end: true },
  { to: "/system", label: "System", icon: "pulse", end: false },
  { to: "/activity", label: "Activity", icon: "history", end: false },
  { to: "/help", label: "Help", icon: "help", end: false },
];
const serverNav = [
  { path: "overview", label: "Overview", icon: "grid" },
  { path: "console", label: "Console", icon: "terminal" },
  { path: "players", label: "Players", icon: "users" },
  { path: "mods", label: "Mods and plugins", icon: "blocks" },
  { path: "backups", label: "Backups", icon: "package" },
  { path: "files", label: "Files", icon: "folder" },
  { path: "schedule", label: "Schedule", icon: "clock" },
  { path: "settings", label: "Settings", icon: "sliders" },
];

export function AppShell({ onLogout }: { onLogout: () => void }) {
  const { pathname } = useLocation();
  const match = useMatch("/servers/:profileId/*");
  const profileId = match?.params.profileId ?? "";
  const navRef = useRef<HTMLElement>(null);
  // Each page is its own route now, so it should open at the top rather than inherit
  // the scroll position of the page the owner came from.
  useEffect(() => { window.scrollTo({ top: 0, behavior: "instant" }); }, [pathname]);
  // Keep the open server's tools reachable from Servers and System too, so leaving a
  // workspace is never a one-way trip.
  const [recentId, setRecentId] = useState("");
  useEffect(() => { if (profileId) setRecentId(profileId); }, [profileId]);
  const state = useQuery({ queryKey: ["state"], queryFn: () => api<ProcessState>("/server/state"), refetchInterval: 1000 });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api<Profile[]>("/profiles") });
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: () => api<LocalNotifications>("/notifications"), refetchInterval: 30_000 });
  const profile = profiles.data?.find(entry => entry.id === (profileId || recentId));
  // On narrow screens the sidebar becomes a horizontally scrolling row; without
  // this, landing on a page whose nav item sits off-screen gives no clue where
  // you are or that there is more to scroll to. The server nav only exists once
  // `profile` resolves, which can happen after `pathname` already settled, so
  // this must also re-run once that nav actually appears.
  useEffect(() => {
    navRef.current?.querySelector<HTMLElement>("a.active")?.scrollIntoView({
      behavior: "instant" as ScrollBehavior, inline: "center", block: "nearest",
    });
  }, [pathname, profile]);
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
        <nav aria-label="Main navigation" ref={navRef}>
          <p className="nav-heading">Workspace</p>
          {workspaceNav.map(item => <NavLink key={item.to} to={item.to} end={item.end} data-walkthrough={item.label.toLowerCase()} className={({ isActive }) => isActive ? "active" : ""}><NavIcon name={item.icon} /><span>{item.label}</span>{item.to === "/activity" && !!notifications.data?.unread_count && <small className="nav-count" aria-label={`${notifications.data.unread_count} notifications`}>{notifications.data.unread_count}</small>}</NavLink>)}
          {profile && <>
            <p className="nav-heading nav-heading--server" title={profile.name}>{profile.name}</p>
            {serverNav.map(item => <NavLink key={item.path} to={`/servers/${profile.id}/${item.path}`} className={({ isActive }) => isActive ? "active" : ""}><NavIcon name={item.icon} /><span>{item.label}</span></NavLink>)}
          </>}
          <span className="sidebar-scroll-hint" aria-hidden="true" />
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
