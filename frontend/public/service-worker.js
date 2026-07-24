// Exists only so the dashboard can be installed as an app. It never caches:
// server state, console logs, and backups must always be current, so every
// request passes straight through to the network untouched.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
