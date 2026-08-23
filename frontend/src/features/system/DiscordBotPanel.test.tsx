import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { DiscordBotPanel } from "./DiscordBotPanel";

const connection = {
  id: "connection-1",
  profile_id: "profile-1",
  profile_name: "Family world",
  application_id: "1535816544951476324",
  guild_id: "900000000000000002",
  channel_id: "900000000000000003",
  owner_user_id: "900000000000000004",
  authorized_user_ids: ["900000000000000004"],
  authorized_role_ids: [],
  enabled: true,
  share_address: false,
  publish_address: false,
  status_message_configured: true,
  last_heartbeat_at: null,
  relay_connection_id: "relay-connection-1",
  relay_connected: true,
  last_relay_heartbeat_at: null,
  last_delivery_result: "delivered" as const,
  last_delivery_at: "2026-08-21T12:00:00+00:00",
  last_delivery_detail: "Status message delivered.",
  created_at: null,
  updated_at: null,
};

const status = {
  application_id: "1535816544951476324",
  public_key_configured: true,
  bot_ready: true,
  relay_configured: true,
  relay_url: "https://relay.example.test",
  relay_online: true,
  discord_online: true,
  installation_id: "installation-1",
  connector_configured: true,
  connector_environment_managed: false,
  legacy_token_present: false,
  install_url: null,
  application_error: null,
  public_key_error: null,
  mode: "central_relay" as const,
  pairings: [],
  connections: [connection],
};

function renderPanel(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><DiscordBotPanel /></QueryClientProvider>);
  return client;
}

function requestBodyHasTrue(body: BodyInit | null | undefined, field: string): boolean {
  if (typeof body !== "string") return false;
  const parsed: unknown = JSON.parse(body);
  return typeof parsed === "object"
    && parsed !== null
    && (parsed as Record<string, unknown>)[field] === true;
}

test("shows owner and safe delivery state and saves approved principals", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (init?.method === "POST") return Promise.resolve(new Response(JSON.stringify(connection), { status: 200 }));
    if (url.endsWith("/profiles")) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify(status), { status: 200 }));
  });
  const client = renderPanel(fetchMock);

  expect(await screen.findByText(/Pairing owner:/)).toBeVisible();
  expect(screen.getByText("900000000000000004")).toBeVisible();
  expect(screen.getByText(/Status message delivered/)).toBeVisible();
  expect(screen.getByText(/Status message delivered/)).toHaveTextContent(
    new Date(connection.last_delivery_at).toLocaleString(),
  );
  const userInput = screen.getByLabelText(/Approved user IDs/);
  fireEvent.change(userInput, { target: { value: "900000000000000006" } });
  fireEvent.click(screen.getByRole("button", { name: "Save approved principals" }));
  await waitFor(() => expect(calls.some(call => call.init?.method === "POST")).toBe(true));
  const request = calls.find(call => call.init?.method === "POST");
  expect(typeof request?.init?.body).toBe("string");
  expect(JSON.parse(request?.init?.body as string)).toEqual({
    authorized_user_ids: ["900000000000000004", "900000000000000006"],
    authorized_role_ids: [],
  });
  client.clear();
  vi.unstubAllGlobals();
});

test("offers connector rotation with explicit confirmation", async () => {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "POST") return Promise.resolve(new Response(JSON.stringify({ installation_id: "installation-1", rotation_state: "reconnecting", detail: "Connector rotated safely." }), { status: 200 }));
    if (url.endsWith("/profiles")) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify(status), { status: 200 }));
  });
  vi.stubGlobal("confirm", vi.fn(() => true));
  const client = renderPanel(fetchMock);
  fireEvent.click(await screen.findByRole("button", { name: "Rotate connector identity" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/discord/connector/rotate",
    expect.objectContaining({ method: "POST" }),
  ));
  client.clear();
  vi.unstubAllGlobals();
});

test("rejects invalid approved principal input without making a request", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith("/profiles")) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify(status), { status: 200 }));
  });
  const client = renderPanel(fetchMock);

  const userInput = await screen.findByLabelText(/Approved user IDs/);
  fireEvent.change(userInput, { target: { value: "not-a-snowflake" } });
  fireEvent.click(screen.getByRole("button", { name: "Save approved principals" }));

  expect(await screen.findByRole("status")).toHaveTextContent(/17–20 digit/);
  expect(calls.some(call => call.init?.method === "POST")).toBe(false);
  client.clear();
  vi.unstubAllGlobals();
});

test("shows deployment-managed rotation guidance and no local rotation action", async () => {
  const managedStatus = { ...status, connector_environment_managed: true };
  const fetchMock = vi.fn((url: string) => {
    if (url.endsWith("/profiles")) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify(managedStatus), { status: 200 }));
  });
  const client = renderPanel(fetchMock);

  expect(await screen.findByText("Connector rotation is managed by deployment settings.")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Rotate connector identity" })).toBeNull();
  client.clear();
  vi.unstubAllGlobals();
});

test("shows the exact claimed identity and confirms only after owner review", async () => {
  const pairing = {
    id: "pairing-1",
    profile_id: "profile-1",
    profile_name: "Family world",
    status: "pending" as const,
    expires_at: "2026-08-23T18:10:00+00:00",
    claimed: true,
    claimed_application_id: "1535816544951476324",
    claimed_guild_id: "900000000000000002",
    claimed_channel_id: "900000000000000003",
    claimed_user_id: "900000000000000004",
    claimed_role_ids: ["900000000000000005"],
    claimed_at: "2026-08-23T18:00:00+00:00",
    confirmed_at: null,
  };
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (init?.method === "POST") {
      return Promise.resolve(new Response(JSON.stringify(connection), { status: 200 }));
    }
    if (url.endsWith("/profiles")) {
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    }
    return Promise.resolve(new Response(JSON.stringify({ ...status, pairings: [pairing], connections: [] }), { status: 200 }));
  });
  const confirm = vi.fn(() => true);
  vi.stubGlobal("confirm", confirm);
  const client = renderPanel(fetchMock);

  expect(await screen.findByText(/Observed roles \(not approved automatically\)/)).toHaveTextContent(
    "900000000000000005",
  );
  expect(screen.getByText(/Claiming user:/)).toHaveTextContent("900000000000000004");
  fireEvent.click(screen.getByRole("button", { name: "Review and confirm" }));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Application: 1535816544951476324"));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Channel: 900000000000000003"));
  await waitFor(() => expect(calls.some(call =>
    call.url.endsWith("/discord/pairings/pairing-1/confirm")
    && call.init?.method === "POST"
  )).toBe(true));
  client.clear();
  vi.unstubAllGlobals();
});

test("keeps address sharing and persistent publication as separate controls", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (init?.method === "POST") {
      return Promise.resolve(new Response(JSON.stringify(connection), { status: 200 }));
    }
    if (url.endsWith("/profiles")) {
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    }
    return Promise.resolve(new Response(JSON.stringify(status), { status: 200 }));
  });
  const client = renderPanel(fetchMock);

  const publish = await screen.findByRole("button", { name: "Publish address in status" });
  expect(publish).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Allow /address sharing" }));
  await waitFor(() => expect(calls.some(call =>
    requestBodyHasTrue(call.init?.body, "share_address")
  )).toBe(true));
  client.clear();
  vi.unstubAllGlobals();
});

test("allows persistent publication only after address sharing is enabled", async () => {
  const shared = { ...connection, share_address: true };
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (init?.method === "POST") {
      return Promise.resolve(new Response(JSON.stringify(shared), { status: 200 }));
    }
    if (url.endsWith("/profiles")) {
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    }
    return Promise.resolve(new Response(JSON.stringify({ ...status, connections: [shared] }), { status: 200 }));
  });
  const client = renderPanel(fetchMock);

  fireEvent.click(await screen.findByRole("button", { name: "Publish address in status" }));
  await waitFor(() => expect(calls.some(call =>
    requestBodyHasTrue(call.init?.body, "publish_address")
  )).toBe(true));
  client.clear();
  vi.unstubAllGlobals();
});

test("permits terminal revocation while a connection is disabled", async () => {
  const disabled = { ...connection, enabled: false };
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    if (url.endsWith("/profiles")) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify({ ...status, connections: [disabled] }), { status: 200 }));
  });
  const confirm = vi.fn(() => true);
  vi.stubGlobal("confirm", confirm);
  const client = renderPanel(fetchMock);

  expect(await screen.findByText("Disabled")).toBeVisible();
  const revoke = screen.getByRole("button", { name: "Revoke permanently" });
  expect(revoke).toBeEnabled();
  fireEvent.click(revoke);
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("terminal action"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/discord/connections/connection-1",
    expect.objectContaining({ method: "DELETE" }),
  ));
  client.clear();
  vi.unstubAllGlobals();
});

test("distinguishes relay connectivity from Discord Gateway readiness", async () => {
  const gatewayDown = { ...status, bot_ready: false, discord_online: false };
  const fetchMock = vi.fn((url: string) => {
    if (url.endsWith("/profiles")) return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify(gatewayDown), { status: 200 }));
  });
  const client = renderPanel(fetchMock);

  expect(await screen.findByText("Discord unavailable")).toBeVisible();
  expect(screen.getByText("Connected")).toBeVisible();
  expect(screen.getAllByText("Not ready")).toHaveLength(2);
  client.clear();
  vi.unstubAllGlobals();
});
