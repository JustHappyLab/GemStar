#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$DIR/.env" ]; then set -a; source "$DIR/.env"; set +a; fi
uv run python src/main.py "$@"
