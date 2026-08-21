#!/usr/bin/env bash
# One command to get the Docker Compose deployment running, for someone who
# does not want to think about Docker at all. It checks Docker is installed,
# starts Docker Desktop on macOS if it is not already running, creates
# docker.env from the template on first run, builds and starts the
# container, waits for the dashboard to actually answer (not just for the
# container to launch), then opens it in the default browser.
#
# Safe to run again later: an already-running, healthy Blockstead is
# detected and just opened rather than rebuilt.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

ENV_FILE=docker.env
ENV_EXAMPLE=docker.env.example

die() { printf '\n%s\n' "$*" >&2; exit 1; }
log() { printf '%s\n' "$*"; }

open_url() {
  case "$(uname -s)" in
    Darwin) open "$1" ;;
    Linux)
      if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$1" >/dev/null 2>&1 || true
      fi
      ;;
  esac
}

# --- Docker present? ---------------------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
  die "Docker was not found on this computer.

Blockstead's easy setup runs in Docker. Download Docker Desktop from:
  https://www.docker.com/products/docker-desktop/

Install it, open it once, then run this script again."
fi

# --- Docker daemon running? ---------------------------------------------------

if ! docker info >/dev/null 2>&1; then
  case "$(uname -s)" in
    Darwin)
      if [[ -d /Applications/Docker.app ]]; then
        log "Starting Docker Desktop… (this can take a minute the first time)"
        open -a Docker
      else
        die "Docker is installed but Docker Desktop was not found at /Applications/Docker.app.
Open Docker Desktop yourself, then run this script again."
      fi
      ;;
    *)
      die "Docker is installed but not running. Start Docker, then run this script again."
      ;;
  esac

  waited=0
  until docker info >/dev/null 2>&1; do
    if (( waited >= 180 )); then
      die "Docker Desktop did not finish starting within 3 minutes.
Open it from Applications, wait for the whale icon in the menu bar to settle, then run this script again."
    fi
    sleep 2
    waited=$((waited + 2))
  done
  log "Docker is ready."
fi

# --- Configuration file present? ----------------------------------------------

if [[ ! -f $ENV_FILE ]]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  log "Created $ENV_FILE from the template. The dashboard stays private to this computer by default."
fi

# --- Where data and servers live on this computer -----------------------------
# Real folders, not Docker-managed volumes, so Finder/Explorer or your own
# tools can reach them directly. Fill these in on first run (or when
# upgrading a docker.env from before this existed) so they are visible and
# editable rather than an invisible default.

if ! grep -q '^BLOCKSTEAD_HOST_DATA_DIR=' "$ENV_FILE" 2>/dev/null; then
  {
    printf 'BLOCKSTEAD_HOST_DATA_DIR=%s\n' "$HOME/Blockstead/data"
    printf 'BLOCKSTEAD_HOST_SERVERS_DIR=%s\n' "$HOME/Blockstead/servers"
  } >> "$ENV_FILE"
  log "Blockstead's data and servers will live in $HOME/Blockstead (edit $ENV_FILE to use a different folder)."
fi

host_data_dir=$(grep -E '^BLOCKSTEAD_HOST_DATA_DIR=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
host_servers_dir=$(grep -E '^BLOCKSTEAD_HOST_SERVERS_DIR=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
[[ -n $host_data_dir ]] || host_data_dir="$root/blockstead-data"
[[ -n $host_servers_dir ]] || host_servers_dir="$root/blockstead-servers"
mkdir -p "$host_data_dir" "$host_servers_dir"

# A one-time bridge for anyone whose data is still in this project's old
# Docker-managed volumes, from before real folders were the default. Only
# acts when the new folder is empty and the old volume still exists, so it
# never overwrites or merges anything unexpected.
migrate_named_volume() {
  local volume=$1 host_dir=$2
  [[ -z $(ls -A "$host_dir" 2>/dev/null) ]] || return 0
  docker volume inspect "$volume" >/dev/null 2>&1 || return 0
  log "Found data in the old Docker-managed volume '$volume' — copying it into $host_dir (one-time)…"
  docker run --rm -v "$volume:/from:ro" -v "$host_dir:/to" alpine:3 sh -c 'cp -a /from/. /to/' \
    || die "Could not copy data from the old '$volume' volume into $host_dir.
Nothing was changed. That volume still has your data; inspect it with: docker volume inspect $volume"
  log "Copied. The old '$volume' volume is no longer used and can be removed later with: docker volume rm $volume"
}

migrate_named_volume blockstead_blockstead-data "$host_data_dir"
migrate_named_volume blockstead_blockstead-servers "$host_servers_dir"

dash_host=$(grep -E '^BLOCKSTEAD_DASHBOARD_BIND=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
dash_port=$(grep -E '^BLOCKSTEAD_DASHBOARD_PORT=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
[[ -n $dash_host ]] || dash_host=127.0.0.1
[[ -n $dash_port ]] || dash_port=8765
# 0.0.0.0 means "reachable from the LAN too," not a browsable address by
# itself; this computer can always also reach it at 127.0.0.1.
[[ $dash_host == 0.0.0.0 ]] && dash_host=127.0.0.1
dashboard_url="http://${dash_host}:${dash_port}"

health() { curl --fail --silent --max-time 3 "$dashboard_url/api/v1/health" 2>/dev/null; }

# --- Build and start, unless it is already healthy ----------------------------

if [[ -n $(health) ]]; then
  log "Blockstead is already running."
else
  log "Building Blockstead… the first run downloads a Java runtime and builds the dashboard, so this can take several minutes. Later runs are fast."
  if ! docker compose --env-file "$ENV_FILE" up --build -d; then
    die "Blockstead did not start. Recent logs:

$(docker compose --env-file "$ENV_FILE" logs --tail 30 blockstead 2>/dev/null)

See the full log with: docker compose logs -f blockstead"
  fi

  log "Waiting for the dashboard to answer…"
  waited=0
  until [[ -n $(health) ]]; do
    if (( waited >= 120 )); then
      die "The dashboard did not answer within 2 minutes. Recent logs:

$(docker compose --env-file "$ENV_FILE" logs --tail 40 blockstead 2>/dev/null)

See the full log with: docker compose logs -f blockstead"
    fi
    sleep 2
    waited=$((waited + 2))
  done
fi

# --- Point the way and open it -------------------------------------------------

setup_status=$(curl --fail --silent --max-time 3 "$dashboard_url/api/v1/setup/status" 2>/dev/null || true)
if [[ $setup_status == *'"needs_setup":true'* ]]; then
  log "Blockstead is ready. Create your administrator account at $dashboard_url"
else
  log "Blockstead is ready at $dashboard_url"
fi

open_url "$dashboard_url"
