#!/usr/bin/env bash
# The installer builds the virtual environment in a staging directory beside
# /opt/blockstead and then exchanges the two trees, so the tree the service
# starts from is never the tree the environment was built in. A virtual
# environment console script (venv/bin/uvicorn and friends) records the
# absolute interpreter path it was built with, which means a unit that starts
# one of those scripts starts a Python that is deleted with the superseded
# tree: the dashboard then dies at exec time, before it can log anything.
#
# This models that publish step with a stand-in environment — no Docker, no
# systemd, no network — and requires the shipped unit to survive it.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
unit=$root/packaging/systemd/blockstead.service
app_dir=/opt/blockstead

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

staged=$workdir/blockstead.incoming.test
published=$workdir/blockstead
mkdir -p "$staged/venv/bin"

# What "python3 -m venv" leaves behind: an interpreter symlinked out to the
# system Python, which keeps working wherever the tree is published.
ln -s "$(command -v python3)" "$staged/venv/bin/python"
# What "pip install" leaves behind: a script pinned to the absolute path the
# environment happened to occupy while it was being built.
printf '#!%s\n' "$staged/venv/bin/python" >"$staged/venv/bin/uvicorn"
printf 'raise SystemExit(0)\n' >>"$staged/venv/bin/uvicorn"
chmod +x "$staged/venv/bin/uvicorn"

mv "$staged" "$published"

exec_line=$(sed -n 's/^ExecStart=//p' "$unit" | head -n 1)
[[ -n $exec_line ]] || { echo "FAIL: the unit has no ExecStart line." >&2; exit 1; }
program=${exec_line%% *}
case $program in
  "$app_dir"/*) ;;
  *) echo "FAIL: ExecStart does not start a program from $app_dir: $program" >&2; exit 1 ;;
esac
program=$published/${program#"$app_dir"/}

if [[ ! -x $program ]]; then
  echo "FAIL: the published tree has no runnable $program." >&2
  exit 1
fi
if [[ $(head -c 2 "$program") == '#!' ]]; then
  interpreter=$(sed -n '1s|^#!\([^[:space:]]*\).*|\1|p' "$program")
  if [[ ! -x $interpreter ]]; then
    echo "FAIL: the service starts $program, whose interpreter $interpreter does not survive" >&2
    echo "      publishing. Start the interpreter directly instead of a console script." >&2
    exit 1
  fi
fi

echo "PASS: the service start program survives the staged-tree exchange"
