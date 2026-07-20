import type { ExtensionEntry, SharedMapView } from "../../api/client";
import { Button } from "../../components/Button";

export const SHARED_MAP_PROJECT_ID = "squaremap";

function configuredMapUrl(port: number): string {
  const hostname = window.location.hostname || "server-address";
  const host = hostname.includes(":") && !hostname.startsWith("[")
    ? `[${hostname}]`
    : hostname;
  return `http://${host}:${port}`;
}

function isSquaremap(entry: ExtensionEntry): boolean {
  return entry.identifier?.toLowerCase() === SHARED_MAP_PROJECT_ID
    || entry.display_name?.toLowerCase() === SHARED_MAP_PROJECT_ID;
}

export function SharedMapCard({
  entries,
  disabledEntries,
  map,
  stopped,
  busy,
  install,
}: {
  entries: ExtensionEntry[];
  disabledEntries: ExtensionEntry[];
  map?: SharedMapView;
  stopped: boolean;
  busy: boolean;
  install: () => void;
}) {
  const installed = entries.some(isSquaremap);
  const disabled = disabledEntries.some(isSquaremap);
  const mapUrl = configuredMapUrl(map?.port ?? 8080);
  const localAddress = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(window.location.hostname);

  return <aside className="shared-map-card" aria-labelledby="shared-map-title">
    <div>
      <p className="eyebrow">Recommended shared map</p>
      <h3 id="shared-map-title">squaremap</h3>
      <p>A lightweight 2D map that runs on the server. Players open the same live map in a browser; they do not need to install a client mod.</p>
      <small>Best fit for a small Linux host. Initial rendering still uses CPU and disk, so avoid a full-world render and cap its render threads after the first startup.</small>
    </div>
    <div className="shared-map-action">
      {installed ? <>
        <strong>Installed</strong>
        {stopped
          ? <span>Start the server to open the map.</span>
          : map?.internal_webserver_enabled === false
            ? <span>squaremap's built-in web server is disabled.</span>
            : <a href={mapUrl} target="_blank" rel="noreferrer">Open map address</a>}
        <small>
          {localAddress
            ? "For other players, replace localhost with this Linux server's LAN address."
            : map?.config_present
              ? `Configured on ${map.bind}:${map.port}.`
              : "Waiting for squaremap to generate config.yml; using its default port, 8080."}
        </small>
        {map?.problem && <small>{map.problem}</small>}
      </> : disabled ? <>
        <strong>Installed but disabled</strong>
        <span>Enable squaremap in the Disabled list below, then start the server.</span>
      </> : <>
        <Button disabled={!stopped || busy} onClick={install}>
          {busy ? "Installing…" : "Install shared map"}
        </Button>
        <small>{stopped ? "Blockstead will select a compatible, checksum-verified Modrinth release." : "Stop the server before installing the map."}</small>
      </>}
    </div>
    <p className="shared-map-network-note">squaremap serves the map on a separate web port. Blockstead does not open the Linux firewall or expose the port through your router.</p>
  </aside>;
}
