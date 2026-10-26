#!/usr/bin/env bash
# Mac-side helpers. deploy: move the Spark's copy to current main. pull: fetch sanitized runs back.
# NOTE: $host:~/evals is now a git clone of this repo, not an rsync mirror. deploy
# fast-forwards it over ssh; commit and push to origin main first, or the pull is a no-op.
set -euo pipefail
host="${DGX_HOST:?set DGX_HOST, e.g. user@host}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  deploy)
    # .harness-commit is the driver's fallback marker when git is unavailable; refresh
    # it locally and on the Spark so both copies carry the deployed commit.
    git -C "$repo" rev-parse HEAD > "$repo/.harness-commit"
    timeout 300 ssh -o BatchMode=yes "$host" \
      'git -C ~/evals pull --ff-only origin main && git -C ~/evals rev-parse HEAD > ~/evals/.harness-commit' ;;
  pull)
    timeout 600 rsync -a -e "ssh -o BatchMode=yes" "$host:evals/runs/" "$repo/runs/"
    timeout 60 rsync -a -e "ssh -o BatchMode=yes" "$host:evals/leaderboard.md" "$repo/leaderboard.md" ;;
  *) echo "usage: DGX_HOST=user@host $0 deploy|pull" >&2; exit 64 ;;
esac
