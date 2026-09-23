import { useEffect, useState } from "react";
import { api, type LogEvent } from "../../api/client";

const KEEP = 400;
const FIRST_RETRY_MS = 1000;
const MAX_RETRY_MS = 30_000;
/** The server closes with this once the login session is no longer valid. */
const SESSION_ENDED = 1008;

/**
 * Stream the server log, reconnecting when the connection drops.
 *
 * Every connection starts by replaying the server's whole buffer, so the first
 * frame of a connection replaces what is shown rather than appending to it.
 */
export function useLiveLogs(): LogEvent[] {
  const [logs, setLogs] = useState<LogEvent[]>([]);

  // A snapshot for when streaming is unavailable; the stream's replay wins.
  useEffect(() => {
    api<LogEvent[]>("/server/logs")
      .then(events => setLogs(current => (current.length ? current : events.slice(-KEEP))))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let delay = FIRST_RETRY_MS;
    let disposed = false;

    function connect() {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const current = new WebSocket(`${protocol}://${location.host}/api/v1/server/logs/ws`);
      socket = current;
      let replaying = true;
      current.onopen = () => { delay = FIRST_RETRY_MS; };
      current.onmessage = event => {
        const payload: unknown = event.data;
        if (typeof payload !== "string") return;
        let parsed: LogEvent;
        try {
          parsed = JSON.parse(payload) as LogEvent;
        } catch {
          return; // Ignore invalid frames safely
        }
        const replace = replaying;
        replaying = false;
        setLogs(existing => (replace ? [parsed] : [...existing.slice(-(KEEP - 1)), parsed]));
      };
      current.onclose = event => {
        if (disposed || event.code === SESSION_ENDED) return;
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, MAX_RETRY_MS);
      };
    }

    connect();
    return () => {
      disposed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, []);

  return logs;
}
