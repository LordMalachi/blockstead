import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles/index.css";

const client = new QueryClient({ defaultOptions: { queries: { retry: 1 }, mutations: { retry: false } } });
createRoot(document.getElementById("root")!).render(<StrictMode><QueryClientProvider client={client}><BrowserRouter><App /></BrowserRouter></QueryClientProvider></StrictMode>);

// Registering this makes the dashboard installable; the worker itself never
// caches, so it cannot serve stale server state.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => { void navigator.serviceWorker.register("/service-worker.js"); });
}
