#!/usr/bin/env bash
set -euo pipefail

cd /Users/ken/workspace/GemStar
STATUS_MD="artifacts/current/trade_status.md"
STATUS_JSON="artifacts/current/trade_status.json"
TODAY="$(date +%Y%m%d)"

print_freshness() {
  local path="$1"
  local ref_date=""
  if [[ -f "${STATUS_JSON}" ]]; then
    ref_date="$(uv run python - <<'PY' 2>/dev/null || true
import json
from pathlib import Path

path = Path("artifacts/current/trade_status.json")
try:
    data = json.loads(path.read_text())
except Exception:
    data = {}
print(data.get("ref_date") or data.get("as_of_date") or "")
PY
)"
  fi
  if [[ -z "${ref_date}" && -f "${STATUS_MD}" ]]; then
    ref_date="$(sed -n 's/^- 日期：//p' "${STATUS_MD}" | head -1)"
  fi

  echo "GemStar status source: ${path}"
  echo "GemStar status updated_at: $(date -r "${path}" '+%Y-%m-%d %H:%M:%S %Z')"
  if [[ -n "${ref_date}" ]]; then
    echo "GemStar status ref_date: ${ref_date}"
    if [[ "${ref_date}" != "${TODAY}" ]]; then
      echo "WARNING: GemStar status is stale for today (${TODAY}); latest completed status is ${ref_date}."
      echo "If a GemStar run is currently in progress, wait until it writes artifacts/current/trade_status.*."
    fi
  fi
  echo
}

if [[ -f "${STATUS_MD}" ]]; then
  print_freshness "${STATUS_MD}"
  cat "${STATUS_MD}"
elif [[ -f "${STATUS_JSON}" ]]; then
  print_freshness "${STATUS_JSON}"
  cat "${STATUS_JSON}"
else
  echo "GemStar has not generated artifacts/current/trade_status.md yet."
  echo "Run: uv run python -m src.cli.app trade --once"
fi
