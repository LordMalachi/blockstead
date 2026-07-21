#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image=blockstead-native-update-contract

command -v docker >/dev/null 2>&1 || {
  echo "Docker is required for the disposable native updater integration test." >&2
  exit 1
}

docker build \
  --file "$root/tests/integration/native-update.Dockerfile" \
  --tag "$image" \
  "$root"
docker run --rm "$image"
docker run --rm "$image" bash tests/integration/install-linux-rollback-test.sh
