import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import type { LogEvent } from "../../api/client";
import { useLiveLogs } from "./useLiveLogs";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }

  close() { this.closed = true; }

  deliver(...events: LogEvent[]) {
    act(() => {
      this.onopen?.();
      for (const event of events) this.onmessage?.({ data: JSON.stringify(event) });
    });
  }

  drop(code = 1006) {
    act(() => { this.onclose?.({ code }); });
  }
}

const line = (sequence: number): LogEvent => ({
  sequence,
  timestamp: "2026-09-22T12:00:00Z",
  line: `line ${sequence}`,
  profile_id: "profile-1",
});

function serveSnapshot(events: LogEvent[]) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(
    new Response(JSON.stringify(events), { status: 200, headers: { "Content-Type": "application/json" } }),
  )));
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("the stream's replay replaces the snapshot instead of repeating it", async () => {
  serveSnapshot([line(1), line(2)]);
  const { result } = renderHook(() => useLiveLogs());
  await waitFor(() => expect(result.current).toHaveLength(2));

  FakeSocket.instances[0].deliver(line(1), line(2), line(3));

  expect(result.current.map(entry => entry.sequence)).toEqual([1, 2, 3]);
});

test("a dropped stream reconnects and shows the fresh replay", () => {
  serveSnapshot([]);
  vi.useFakeTimers();
  const { result } = renderHook(() => useLiveLogs());
  const first = FakeSocket.instances[0];
  first.deliver(line(1), line(2));

  first.drop();
  expect(FakeSocket.instances).toHaveLength(1);
  act(() => { vi.advanceTimersByTime(1000); });
  expect(FakeSocket.instances).toHaveLength(2);

  // A restarted Blockstead numbers its buffer from 1 again.
  FakeSocket.instances[1].deliver(line(1), line(2), line(3));
  expect(result.current.map(entry => entry.sequence)).toEqual([1, 2, 3]);
});

test("it stops reconnecting once the session ends or the page closes", () => {
  serveSnapshot([]);
  vi.useFakeTimers();
  const { unmount } = renderHook(() => useLiveLogs());

  FakeSocket.instances[0].drop(1008);
  act(() => { vi.advanceTimersByTime(60_000); });
  expect(FakeSocket.instances).toHaveLength(1);

  unmount();
  expect(FakeSocket.instances[0].closed).toBe(true);
});
