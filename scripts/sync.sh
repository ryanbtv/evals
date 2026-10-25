#!/usr/bin/env bash
# Mac-side helpers. deploy: copy the harness to dgx01. pull: fetch sanitized runs back.
set -euo pipefail
host="${DGX_HOST:?set DGX_HOST, e.g. user@host}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  deploy)
    git -C "$repo" rev-parse HEAD > "$repo/.harness-commit"
    timeout 300 rsync -a --delete -e "ssh -o BatchMode=yes" \
      --exclude .git --exclude raw-runs --exclude smoke-runs --exclude runs --exclude leaderboard.md \
      "$repo/" "$host:evals/" ;;
  pull)
    timeout 600 rsync -a -e "ssh -o BatchMode=yes" "$host:evals/runs/" "$repo/runs/"
    timeout 60 rsync -a -e "ssh -o BatchMode=yes" "$host:evals/leaderboard.md" "$repo/leaderboard.md" ;;
  *) echo "usage: DGX_HOST=user@host $0 deploy|pull" >&2; exit 64 ;;
esac
