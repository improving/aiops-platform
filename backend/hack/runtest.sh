#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

export TEST_MODE=true
# The tests call the API without tokens; conftest.py sets the same default.
export AUTH_MODE="${AUTH_MODE:-disabled}"

# Per-test SQLite databases live in tmp/
mkdir -p tmp
rm -f tmp/*.db

if [ "${1:-}" == "--help" ] || [ "${1:-}" == "-h" ]; then
    echo "Usage: ./hack/runtest.sh [--update-snapshots | -u] [--cleanup | -c] [pytest args...]"
    echo -e "\nOptions:\n"
    echo "--update-snapshots: Update the snapshots when tests are run"
    echo -e "--cleanup: Cleanup all existing snapshots\n"
    exit 0
fi

# Remove every snapshot directory
if [ "${1:-}" == "--cleanup" ] || [ "${1:-}" == "-c" ]; then
    find . -path ./.venv -prune -o -type d -name "snapshots" -print -exec rm -r {} +
    exit 0
fi

# Regenerate snapshots
if [ "${1:-}" == "--update-snapshots" ] || [ "${1:-}" == "-u" ]; then
    shift
    exec uv run pytest --snapshot-update "$@" .
fi

exec uv run pytest "$@" .
